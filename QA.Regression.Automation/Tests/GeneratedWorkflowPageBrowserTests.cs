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
        var workflowPage = new GeneratedWorkflowPage(Page) { ExportDownloadTimeoutMs = 3000 };

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
    public async Task ExportWaitsForItsGridToFinishLoadingButIgnoresOtherBusyGrids()
    {
        await RouteExportPageAsync("https://grid-loading.example.test/", """
            <div class='k-grid' id='grid'>
                <div class='k-grid-toolbar'><a class='k-grid-excel' onclick='exportGrid()'>Export to Excel</a></div>
                <div class='k-loading-mask' style='width:20px;height:20px'></div>
            </div>
            <div class='k-grid' id='SummaryTablePayment'><div class='k-loading-mask' style='width:20px;height:20px'></div></div>
            <script>
                window.jQuery = element => element;
                window.kendo = { widgetInstance: element => element && element.widget };
                const grid = document.getElementById('grid');
                grid.widget = { dataSource: { _requestInProgress: true } };
                document.getElementById('SummaryTablePayment').widget = { dataSource: { _requestInProgress: true } };
                setTimeout(() => {
                    grid.widget.dataSource._requestInProgress = false;
                    grid.querySelector('.k-loading-mask').remove();
                }, 2000);
                function exportGrid() {
                    if (grid.widget.dataSource._requestInProgress) { window.exportDropped = true; return; }
                    location.href = '/export';
                }
            </script>
            """);

        await new GeneratedWorkflowPage(Page).ClickButtonAsync("Export to Excel");

        Assert.That(await Page.EvaluateAsync<bool>("() => window.exportDropped === true"), Is.False);
        Assert.That(
            await Page.Locator("#automation-excel-download-evidence").InnerTextAsync(),
            Does.Contain("grid-export.xlsx"));
    }

    [Test]
    public async Task ExportFailsFastWithThePageMessageWhenNoFileIsProduced()
    {
        await Page.SetContentAsync("""
            <button onclick="document.body.insertAdjacentHTML('beforeend', '<div class=swal2-popup>There are no records to export</div>')">
                Export to Excel
            </button>
            """);
        var workflowPage = new GeneratedWorkflowPage(Page) { ExportDownloadTimeoutMs = 60000 };
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();

        var exception = Assert.ThrowsAsync<InvalidOperationException>(
            () => workflowPage.ClickButtonAsync("Export to Excel"));

        Assert.That(exception!.Message, Does.Contain("There are no records to export"));
        Assert.That(stopwatch.Elapsed, Is.LessThan(TimeSpan.FromSeconds(20)));
    }

    [Test]
    public async Task ExportReportsAControlThatStaysDisabled()
    {
        await Page.SetContentAsync(
            "<div class='k-grid'><a class='k-grid-excel' style='pointer-events:none;opacity:0.5'>Export to Excel</a></div>");
        var workflowPage = new GeneratedWorkflowPage(Page) { ExportReadyTimeoutMs = 3000 };

        var exception = Assert.ThrowsAsync<InvalidOperationException>(
            () => workflowPage.ClickButtonAsync("Export to Excel"));

        Assert.That(exception!.Message, Does.Contain("stayed unavailable"));
    }

    [TestCase("Jan-2025")]
    [TestCase("January 2025")]
    [TestCase("01/2025")]
    public async Task SelectOptionAsyncPicksAMonthInAReadOnlyBootstrapMonthPicker(string value)
    {
        await Page.SetContentAsync("""
            <div class='input-group'><span class='input-group-addon'>Select Date</span>
                <input id='toMonthYear' class='form-control datestyle' readonly value='Nov-2026' onclick='openPicker()'></div>
            <div class='datepicker datepicker-dropdown dropdown-menu' style='display:none'>
                <div class='datepicker-months'><table>
                    <thead><tr><th class='prev'>&laquo;</th><th class='datepicker-switch'>2026</th><th class='next disabled'>&raquo;</th></tr></thead>
                    <tbody><tr><td id='months'></td></tr></tbody>
                </table></div>
            </div>
            <script>
                const names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                const picker = document.querySelector('.datepicker');
                const yearCell = document.querySelector('.datepicker-switch');
                window.refreshCount = 0;
                document.getElementById('months').innerHTML = names.map(name => `<span class='month'>${name}</span>`).join('');
                function openPicker() { picker.style.display = 'block'; }
                document.querySelector('.prev').onclick = () => yearCell.textContent = Number(yearCell.textContent) - 1;
                document.querySelectorAll('span.month').forEach((span, index) => span.onclick = () => {
                    document.getElementById('toMonthYear').value = `${names[index]}-${yearCell.textContent}`;
                    picker.style.display = 'none';
                    window.refreshCount++;
                });
            </script>
            """);

        await new GeneratedWorkflowPage(Page).SelectOptionAsync("Select Date", value);

        Assert.That(await Page.Locator("#toMonthYear").InputValueAsync(), Is.EqualTo("Jan-2025"));
        Assert.That(await Page.EvaluateAsync<int>("() => window.refreshCount"), Is.EqualTo(1));
        Assert.That(await Page.Locator(".datepicker").IsVisibleAsync(), Is.False);
    }

    [Test]
    public async Task GoToAsyncOpensTheMenuLinkWhenTheTestCaseUrlReturnsNotFound()
    {
        await Page.RouteAsync("https://menu-fallback.example.test/**", async route =>
        {
            var path = new Uri(route.Request.Url).AbsolutePath;
            await route.FulfillAsync(path switch
            {
                "/" => new RouteFulfillOptions
                {
                    ContentType = "text/html",
                    Body = "<nav><span>Utilities</span><ul style='display:none'>"
                        + "<li><a href='/SystemManagement/UserAnalytics'> Portal  Usage Report </a></li></ul></nav>",
                },
                "/SystemManagement/UserAnalytics" => new RouteFulfillOptions
                {
                    ContentType = "text/html",
                    Body = "<h2>Portal Usage Report</h2>",
                },
                _ => new RouteFulfillOptions { Status = 404, ContentType = "text/html", Body = "Not found" },
            });
        });
        var workflowPage = new GeneratedWorkflowPage(Page);

        await workflowPage.GoToAsync("https://menu-fallback.example.test/PortalUsageReport", "Portal Usage Report");

        Assert.That(new Uri(Page.Url).AbsolutePath, Is.EqualTo("/SystemManagement/UserAnalytics"));
        var exception = Assert.ThrowsAsync<InvalidOperationException>(
            () => workflowPage.GoToAsync("https://menu-fallback.example.test/Missing"));
        Assert.That(exception!.Message, Does.Contain("HTTP 404"));
    }

    [TestCase("Jan-2026", 2026, 1)]
    [TestCase("September 2019", 2019, 9)]
    [TestCase("06/2019", 2019, 6)]
    public void ParseMonthYearAcceptsCommonMonthFormats(string value, int year, int month)
    {
        Assert.That(GeneratedWorkflowPage.ParseMonthYear(value), Is.EqualTo(new DateTime(year, month, 1)));
    }

    private async Task RouteExportPageAsync(string pageUrl, string body)
    {
        await Page.RouteAsync(pageUrl + "**", async route =>
        {
            if (new Uri(route.Request.Url).AbsolutePath == "/export")
            {
                await route.FulfillAsync(new RouteFulfillOptions
                {
                    ContentType = "application/vnd.ms-excel",
                    Headers = new Dictionary<string, string>
                    {
                        ["Content-Disposition"] = "attachment; filename=\"grid-export.xlsx\"",
                    },
                    Body = "grid rows",
                });
                return;
            }

            await route.FulfillAsync(new RouteFulfillOptions { ContentType = "text/html", Body = body });
        });
        await Page.GotoAsync(pageUrl);
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
