using Microsoft.Playwright;
using NUnit.Framework;
using QA.Regression.Automation.Pages;
using QA.Regression.Automation.Utilities;

namespace QA.Regression.Automation.Tests;

[TestFixture]
public class GeneratedWorkflowPageBrowserTests : BaseTest
{
    [TestCase("<a href='/export'>Export to Excel</a>")]
    [TestCase("<a class='k-grid-excel' href='/export'><span>Export to Excel</span></a>")]
    [TestCase("<a class='k-grid-excel' title='Export to Excel' href='/export'><span>Excel</span></a>")]
    [TestCase("<button onclick=\"location.href='/export'\">Export to excel</button>")]
    public async Task ExportToExcelClicksVisibleToolbarControlIgnoringHiddenDuplicates(string control)
    {
        const string pageUrl = "https://export-toolbar.example.test/";
        var exportRequests = 0;
        await Page.RouteAsync("https://export-toolbar.example.test/**", async route =>
        {
            if (new Uri(route.Request.Url).AbsolutePath == "/export")
            {
                exportRequests++;
                await route.FulfillAsync(new RouteFulfillOptions
                {
                    ContentType = "application/vnd.ms-excel",
                    Headers = new Dictionary<string, string>
                    {
                        ["Content-Disposition"] = "attachment; filename=\"toolbar-report.xls\"",
                    },
                    Body = "exported rows",
                });
                return;
            }

            await route.FulfillAsync(new RouteFulfillOptions
            {
                ContentType = "text/html",
                Body = "<button style='display:none'>Export to Excel</button>"
                    + "<a class='k-grid-excel' style='display:none'>Export to Excel</a>"
                    + control,
            });
        });
        await Page.GotoAsync(pageUrl);
        await new GeneratedWorkflowPage(Page).ClickButtonAsync("Export to Excel");

        Assert.That(exportRequests, Is.EqualTo(1));
        Assert.That(
            await Page.Locator("#automation-excel-download-evidence").InnerTextAsync(),
            Does.Contain("toolbar-report.xls"));
    }

    [TestCase("report.xlsx", "export data", true)]
    [TestCase("report.xls", "export data", true)]
    [TestCase("report.txt", "not Excel", false)]
    [TestCase("report.xlsx", "", false)]
    public async Task ExportToExcelRequiresANonEmptyExcelDownload(
        string filename, string content, bool expectedSuccess)
    {
        const string pageUrl = "https://export.example.test/";
        await Page.RouteAsync("https://export.example.test/**", async route =>
        {
            if (new Uri(route.Request.Url).AbsolutePath == "/export")
            {
                await route.FulfillAsync(new RouteFulfillOptions
                {
                    ContentType = "application/octet-stream",
                    Headers = new Dictionary<string, string>
                    {
                        ["Content-Disposition"] = $"attachment; filename=\"{filename}\"",
                    },
                    Body = content,
                });
                return;
            }

            await route.FulfillAsync(new RouteFulfillOptions
            {
                ContentType = "text/html",
                Body = "<button onclick=\"location.href='/export'\">Export to Excel</button>",
            });
        });
        await Page.GotoAsync(pageUrl);
        var workflowPage = new GeneratedWorkflowPage(Page);

        if (expectedSuccess)
        {
            await workflowPage.ClickButtonAsync("Export to Excel");
            var evidence = Page.Locator("#automation-excel-download-evidence");
            Assert.That(await evidence.IsVisibleAsync(), Is.True);
            var evidenceText = await evidence.InnerTextAsync();
            Assert.That(evidenceText, Does.Contain($"File: {filename}"));
            Assert.That(evidenceText, Does.Contain($"Size: {System.Text.Encoding.UTF8.GetByteCount(content)} bytes"));
            Assert.That(evidenceText, Does.Contain("Download completed and saved"));
        }
        else
        {
            Assert.ThrowsAsync<AssertionException>(async () =>
            {
                using var isolatedContext = new NUnit.Framework.Internal.TestExecutionContext.IsolatedContext();
                await workflowPage.ClickButtonAsync("Export to Excel");
            });
            Assert.That(await Page.Locator("#automation-excel-download-evidence").CountAsync(), Is.Zero);
        }
    }

    [Test]
    public async Task ExportToExcelFailsWhenClickDoesNotDownloadAFile()
    {
        await Page.SetContentAsync("<button>Export to Excel</button>");
        var workflowPage = new GeneratedWorkflowPage(Page);

        Assert.ThrowsAsync<TimeoutException>(
            () => workflowPage.ClickButtonAsync("Export to Excel"));
    }

    [Test]
    public async Task SelectOptionAsyncSetsLabelledFiltersBeforeExportBecomesAvailable()
    {
        const string pageUrl = "https://filters.example.test/";
        await Page.RouteAsync("https://filters.example.test/**", async route =>
        {
            if (new Uri(route.Request.Url).AbsolutePath == "/export")
            {
                await route.FulfillAsync(new RouteFulfillOptions
                {
                    ContentType = "application/vnd.ms-excel",
                    Headers = new Dictionary<string, string>
                    {
                        ["Content-Disposition"] = "attachment; filename=\"filtered.xlsx\"",
                    },
                    Body = "filtered rows",
                });
                return;
            }

            await route.FulfillAsync(new RouteFulfillOptions
            {
                ContentType = "text/html",
                Body = """
                    <table><tr><th>Country</th></tr></table>
                    <label for='country'>Country:</label>
                    <select id='country' onchange='refresh()'>
                        <option value=''>Choose</option><option value='FR'>France (FR)</option><option value='GB'>United Kingdom (GB)</option>
                    </select>
                    <div class='row'><div><span>Energy Service</span></div>
                        <div><span class='k-dropdown' role='combobox' tabindex='0'
                            onclick="document.getElementById('services').style.display='block'"><span id='service'>Select</span></span></div></div>
                    <ul id='services' role='listbox' style='display:none'>
                        <li role='option' onclick="pick('Electricity')">Electricity</li><li role='option' onclick="pick('All')">All</li>
                    </ul>
                    <div><div>Select Date</div><div><input id='date' type='text' onchange='refresh()'></div></div>
                    <div id='toolbar'></div>
                    <script>
                        function pick(value) {
                            document.getElementById('service').textContent = value;
                            document.getElementById('services').style.display = 'none';
                            refresh();
                        }
                        function refresh() {
                            const ready = document.getElementById('country').value === 'GB'
                                && document.getElementById('service').textContent === 'All'
                                && document.getElementById('date').value === 'Jan-2026';
                            document.getElementById('toolbar').innerHTML = ready
                                ? "<a class='k-grid-excel' href='/export'>Export to Excel</a>" : '';
                        }
                    </script>
                    """,
            });
        });
        await Page.GotoAsync(pageUrl);
        var workflowPage = new GeneratedWorkflowPage(Page);

        await workflowPage.SelectOptionAsync("Country", "GB");
        await workflowPage.SelectOptionAsync("Energy Service", "All");
        await workflowPage.SelectOptionAsync("Select Date", "Jan-2026");
        await workflowPage.ClickButtonAsync("Export to Excel");

        Assert.That(await Page.Locator("#country").InputValueAsync(), Is.EqualTo("GB"));
        Assert.That(
            await Page.Locator("#automation-excel-download-evidence").InnerTextAsync(),
            Does.Contain("filtered.xlsx"));
    }

    [Test]
    public async Task SelectOptionAsyncReportsAvailableOptionsWhenValueIsMissing()
    {
        await Page.SetContentAsync(
            "<label for='period'>Period</label><select id='period'><option>05/2019</option><option>07/2019</option></select>");
        var workflowPage = new GeneratedWorkflowPage(Page);

        var exception = Assert.ThrowsAsync<InvalidOperationException>(
            () => workflowPage.SelectOptionAsync("Period", "06/2019"));
        Assert.That(exception!.Message, Does.Contain("'05/2019', '07/2019'"));
    }

    [TestCase(new[] { "GB", "United Kingdom (GB)" }, "gb", 0)]
    [TestCase(new[] { "France (FR)", "United Kingdom (GB)" }, "GB", 1)]
    [TestCase(new[] { "All services", "All issues" }, "All", -1)]
    public void ChooseOptionIndexPrefersExactThenUniqueWordMatch(string[] options, string wanted, int expected)
    {
        Assert.That(GeneratedWorkflowPage.ChooseOptionIndex(options, wanted), Is.EqualTo(expected));
    }

    [Test]
    public async Task GoToAsyncDoesNotWaitForNetworkIdleWhenPageHasContinuousRequests()
    {
        const string pageUrl = "https://payment-availability.example.test/PaymentAvailability/PaymentAvailabilityIndex";
        const string pageHtml = """
            <html>
                <body>
                    <h1>Payment Availability</h1>
                    <script>
                        window.heartbeatCount = 0;
                        setInterval(() => {
                            window.heartbeatCount++;
                            fetch('/heartbeat?count=' + window.heartbeatCount).catch(() => {});
                        }, 100);
                    </script>
                </body>
            </html>
            """;

        await Page.RouteAsync("https://payment-availability.example.test/**", async route =>
        {
            if (new Uri(route.Request.Url).AbsolutePath == "/heartbeat")
            {
                await route.FulfillAsync(new RouteFulfillOptions { Status = 204 });
                return;
            }

            await route.FulfillAsync(new RouteFulfillOptions
            {
                ContentType = "text/html",
                Body = pageHtml,
            });
        });

        var workflowPage = new GeneratedWorkflowPage(Page);
        await workflowPage.GoToAsync(pageUrl);
        await Page.WaitForFunctionAsync(
            "() => window.heartbeatCount >= 2",
            null,
            new PageWaitForFunctionOptions { Timeout = 5000 });

        Assert.That(
            await Page.GetByRole(AriaRole.Heading, new PageGetByRoleOptions { Name = "Payment Availability" }).IsVisibleAsync(),
            Is.True);
    }

    [Test]
    public async Task GoToAsyncReloadsUnitDetailsWhenGridAndRefreshControlAreDelayed()
    {
        const string pageUrl = "https://unit-details.example.test/UnitDetails/UnitDetail";
        const string pageWithGrid = """
            <html>
                <body>
                    <h1>Unit Details</h1>
                    <table><tbody><tr><td>Market unit</td></tr></tbody></table>
                    <button title="Refresh" onclick="document.body.dataset.refreshed = 'true'">Refresh</button>
                </body>
            </html>
            """;
        var navigationCount = 0;
        await Page.RouteAsync(pageUrl, async route =>
        {
            navigationCount++;
            await route.FulfillAsync(new RouteFulfillOptions
            {
                ContentType = "text/html",
                Body = navigationCount == 1
                    ? "<html><body><h1>Unit Details</h1></body></html>"
                    : pageWithGrid,
            });
        });

        await Page.GotoAsync(pageUrl, new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
        });

        var workflowPage = new GeneratedWorkflowPage(Page);
        await workflowPage.GoToAsync(pageUrl);
        await workflowPage.ClickButtonAsync("Refresh");

        Assert.That(navigationCount, Is.EqualTo(2));
        Assert.That(await Page.Locator("body").GetAttributeAsync("data-refreshed"), Is.EqualTo("true"));
    }
}
