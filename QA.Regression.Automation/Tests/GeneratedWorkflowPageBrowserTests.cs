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
        var workflowPage = new GeneratedWorkflowPage(Page) { SelectorOptionsTimeoutMs = 1000 };

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

    [Test]
    public async Task CaptureWatchedApiResponseUsesThePagesOwnCallMadeAfterTheSelections()
    {
        await RouteDiagnosticsHistoryPageAsync("https://diagnostics.example.test/", callsApi: true);
        var workflowPage = new GeneratedWorkflowPage(Page);

        workflowPage.WatchApiCalls("/Diagnostics/GetAllDiagnosticsSessions");
        await workflowPage.GoToAsync("https://diagnostics.example.test/Diagnostics/History");
        await workflowPage.SelectOptionAsync("Customer", "Americold");
        await workflowPage.SelectOptionAsync("Site", "Dock 2");
        var status = await workflowPage.CaptureWatchedApiResponseStatusAsync();

        Assert.That(status, Is.EqualTo(200));
        var evidence = await Page.Locator("#copilot-api-evidence-panel").InnerTextAsync();
        Assert.That(evidence, Does.Contain("POST"));
        Assert.That(evidence, Does.Contain("Customer = Americold; Site = Dock 2"));
        Assert.That(evidence, Does.Contain("\"customer\": \"7\"").Or.Contain("\"customer\":\"7\""));
        Assert.That(evidence, Does.Contain("\"site\": \"22\"").Or.Contain("\"site\":\"22\""));
    }

    [Test]
    public async Task CaptureWatchedApiResponseFailsClearlyWhenThePageNeverCallsTheApi()
    {
        await RouteDiagnosticsHistoryPageAsync("https://diagnostics-silent.example.test/", callsApi: false);
        var workflowPage = new GeneratedWorkflowPage(Page) { ApiCallTimeoutMs = 2000 };

        workflowPage.WatchApiCalls("/Diagnostics/GetAllDiagnosticsSessions");
        await workflowPage.GoToAsync("https://diagnostics-silent.example.test/Diagnostics/History");
        await workflowPage.SelectOptionAsync("Customer", "Americold");

        var exception = Assert.ThrowsAsync<InvalidOperationException>(
            () => workflowPage.CaptureWatchedApiResponseStatusAsync());
        Assert.That(exception!.Message, Does.Contain("did not call '/Diagnostics/GetAllDiagnosticsSessions'"));
        Assert.That(exception.Message, Does.Contain("Customer = Americold"));
    }

    [Test]
    public async Task SelectOptionAsyncWaitsForPendingPageDataBeforeSelecting()
    {
        await RouteDiagnosticsHistoryPageAsync("https://diagnostics-sites.example.test/", callsApi: true, sitesDelayMs: 2500);
        var workflowPage = new GeneratedWorkflowPage(Page);

        await workflowPage.GoToAsync("https://diagnostics-sites.example.test/Diagnostics/History");
        await workflowPage.SelectOptionAsync("Customer", "Americold");
        await workflowPage.SelectOptionAsync("Site", "All");

        Assert.That(await Page.EvaluateAsync<int>("() => window.customerChanges"), Is.EqualTo(1),
            "The customer should be selected once, after the sites request finished, without needing a re-apply.");
    }

    [Test]
    public async Task SelectOptionAsyncReappliesThePreviousSelectionWhenADependentSelectorStaysEmpty()
    {
        await RouteDiagnosticsHistoryPageAsync(
            "https://diagnostics-late-sites.example.test/", callsApi: true, sitesDelayMs: 0, sitesWithoutRequestMs: 3000);
        var workflowPage = new GeneratedWorkflowPage(Page);

        await workflowPage.GoToAsync("https://diagnostics-late-sites.example.test/Diagnostics/History");
        await workflowPage.SelectOptionAsync("Customer", "Americold");
        await workflowPage.SelectOptionAsync("Site", "Dock 2");

        Assert.That(await Page.Locator("#site-dropdown").InputValueAsync(), Is.EqualTo("22"));
        Assert.That(await Page.Locator("#customer-dropdown").InputValueAsync(), Is.EqualTo("7"));
    }

    // Mirrors diagnostics-history.js: customers load asynchronously, the site list is only filled from
    // already-loaded sites when the customer changes, the sessions API only accepts POST, and the page
    // re-posts the current filter on a refresh timer.
    private async Task RouteDiagnosticsHistoryPageAsync(
        string origin, bool callsApi, int sitesDelayMs = 0, int sitesWithoutRequestMs = -1)
    {
        var page = """
            <h2>Diagnostics</h2>
            <div class='row'>
              <div><span><b>Customer</b></span><select id='customer-dropdown'></select></div>
              <div><span><b>Site</b></span><select id='site-dropdown'></select></div>
            </div>
            <table><tr><th>Session ID</th><th>Customer</th><th>Site</th></tr></table>
            <script>
              const callsApi = CALLS_API;
              const filter = { customer: null, site: null };
              let sites = [];
              window.siteFills = 0;
              window.customerChanges = 0;
              const allSites = [{ id: '21', name: 'Dock 1', customer: '7' }, { id: '22', name: 'Dock 2', customer: '7' }];
              const post = () => callsApi && fetch('/Diagnostics/GetAllDiagnosticsSessions', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(filter) });
              post();
              if (SITES_WITHOUT_REQUEST_MS >= 0) setTimeout(() => { sites = allSites; }, SITES_WITHOUT_REQUEST_MS);
              else fetch('/Common/GetSites').then(response => response.json()).then(result => { sites = result; });
              setTimeout(() => {
                document.getElementById('customer-dropdown').innerHTML =
                  "<option value='3'>ABP</option><option value='7'>Americold</option>";
              }, 300);
              document.getElementById('customer-dropdown').addEventListener('change', event => {
                window.customerChanges++;
                filter.customer = event.target.value;
                filter.site = '-1';
                const matching = sites.filter(site => site.customer === filter.customer);
                const select = document.getElementById('site-dropdown');
                select.innerHTML = '';
                if (matching.length > 0) {
                  window.siteFills++;
                  select.innerHTML = "<option value='-1'>All</option>"
                    + matching.map(site => `<option value='${site.id}'>${site.name}</option>`).join('');
                }
              });
              document.getElementById('site-dropdown').addEventListener('change', event => { filter.site = event.target.value; });
              setInterval(() => { if (filter.customer !== null) post(); }, 1000);
            </script>
            """
            .Replace("CALLS_API", callsApi ? "true" : "false")
            .Replace("SITES_WITHOUT_REQUEST_MS", sitesWithoutRequestMs.ToString());

        await Page.RouteAsync(origin + "**", async route =>
        {
            var path = new Uri(route.Request.Url).AbsolutePath;
            if (path == "/Diagnostics/GetAllDiagnosticsSessions")
            {
                await route.FulfillAsync(route.Request.Method == "POST"
                    ? new RouteFulfillOptions { ContentType = "application/json", Body = route.Request.PostData ?? "null" }
                    : new RouteFulfillOptions { Status = 405 });
                return;
            }

            if (path == "/Common/GetSites")
            {
                await Task.Delay(sitesDelayMs);
                await route.FulfillAsync(new RouteFulfillOptions
                {
                    ContentType = "application/json",
                    Body = "[{\"id\":\"21\",\"name\":\"Dock 1\",\"customer\":\"7\"},{\"id\":\"22\",\"name\":\"Dock 2\",\"customer\":\"7\"}]",
                });
                return;
            }

            await route.FulfillAsync(new RouteFulfillOptions { ContentType = "text/html", Body = page });
        });
    }

    [Test]
    public async Task CaptureApiResponseStatusPostsTheTestCasePayloadWithTheBrowserSession()
    {
        using var server = new LocalHttpServer(request =>
        {
            if (request.Path == "/PaymentAvailability/PaymentAvailabilityIndex")
            {
                return (200, "text/html", "<h2>Payment Availability</h2>", "session=signed-in; Path=/");
            }

            if (request.Path == "/PaymentAvailability/GetPagingRecords" && request.Method == "POST")
            {
                return (200, "application/json", "{\"Data\":[],\"Total\":0}", null);
            }

            return (405, "text/plain", "Method not allowed", null);
        });
        var payload = new List<KeyValuePair<string, string>>
        {
            new("sort", ""),
            new("page", "1"),
            new("filter", "(Email~doesnotcontain~'endeco')"),
            new("Period", "2026-09-01T00:00:00.000Z"),
            new("CountryId", "2"),
        };

        var status = await new GeneratedWorkflowPage(Page).GoToAndCaptureApiResponseStatusAsync(
            server.Url("/PaymentAvailability/PaymentAvailabilityIndex"),
            "/PaymentAvailability/GetPagingRecords",
            payload);

        Assert.That(status, Is.EqualTo(200));
        var apiRequest = server.Requests.Single(request => request.Path == "/PaymentAvailability/GetPagingRecords");
        Assert.That(apiRequest.Method, Is.EqualTo("POST"));
        Assert.That(apiRequest.Headers["content-type"], Does.StartWith("application/x-www-form-urlencoded"));
        Assert.That(apiRequest.Headers["x-requested-with"], Is.EqualTo("XMLHttpRequest"));
        Assert.That(apiRequest.Headers["cookie"], Does.Contain("session=signed-in"));
        var form = apiRequest.Body.Split('&')
            .Select(pair => pair.Split('=', 2))
            .ToDictionary(pair => Uri.UnescapeDataString(pair[0]), pair => Uri.UnescapeDataString(pair[1].Replace('+', ' ')));
        Assert.That(form, Is.EquivalentTo(payload.ToDictionary(field => field.Key, field => field.Value)));
        Assert.That(apiRequest.Body, Does.StartWith("sort=&page=1&filter="), "The payload keeps the Test Case's field order.");

        var evidence = await Page.Locator("#copilot-api-evidence-panel").InnerTextAsync();
        Assert.That(evidence, Does.Contain("POST"));
        Assert.That(evidence, Does.Contain("Payload sent: sort=&page=1&filter=(Email~doesnotcontain~'endeco')&Period=2026-09-01T00:00:00.000Z&CountryId=2"));
        Assert.That(evidence, Does.Contain("Status: 200"));
    }

    [Test]
    public void SummaryPaymentAvailabilityTimeoutOnlyExtendsTheSummaryEndpoint()
    {
        var workflowPage = new GeneratedWorkflowPage(Page);
        foreach (var path in new[]
        {
            "/PaymentAvailability/GetSummaryPaymentAvailability",
            "/paymentavailability/getsummarypaymentavailability/?page=1",
            "https://example.test/PaymentAvailability/GetSummaryPaymentAvailability",
        })
        {
            Assert.That(workflowPage.ResolveApiTimeoutMs(path, 100000), Is.EqualTo(300000));
            Assert.That(workflowPage.ResolveApiTimeoutMs(path, 45000), Is.EqualTo(300000));
        }

        Assert.That(workflowPage.ResolveApiTimeoutMs("/PaymentAvailability/GetPagingRecords", 100000), Is.EqualTo(100000));
        Assert.That(workflowPage.ResolveApiTimeoutMs("/Diagnostics/GetAllDiagnosticsSessions", 45000), Is.EqualTo(45000));
        Assert.That(workflowPage.ResolveApiTimeoutMs("/Other/GetSummaryPaymentAvailability", 45000), Is.EqualTo(45000));
    }

    [Test]
    public async Task CaptureSummaryPaymentAvailabilityWaitsBeyondTheDefaultHttpClientTimeout()
    {
        using var server = new LocalHttpServer(request =>
        {
            if (request.Path == "/PaymentAvailability/GetSummaryPaymentAvailability")
            {
                Thread.Sleep(105000);
                return (200, "application/json", "{\"Data\":[],\"Total\":0}", null);
            }

            return (200, "text/html", "<h2>Payment Availability</h2>", null);
        });

        var status = await new GeneratedWorkflowPage(Page).GoToAndCaptureApiResponseStatusAsync(
            server.Url("/PaymentAvailability/PaymentAvailabilityIndex"),
            "/PaymentAvailability/GetSummaryPaymentAvailability",
            new List<KeyValuePair<string, string>> { new("page", "1") });

        Assert.That(status, Is.EqualTo(200));
        Assert.That(await Page.Locator("#copilot-api-evidence-panel").InnerTextAsync(), Does.Contain("Status: 200"));
    }

    [Test]
    public async Task CaptureWatchedSummaryPaymentAvailabilityUsesTheLongerResponseWait()
    {
        const string origin = "https://summary-wait.example.test";
        await Page.RouteAsync(origin + "/**", async route =>
        {
            if (route.Request.Url.EndsWith("/GetSummaryPaymentAvailability"))
            {
                await Task.Delay(2500);
                await route.FulfillAsync(new() { Status = 200, ContentType = "application/json", Body = "{}" });
            }
            else
            {
                await route.FulfillAsync(new()
                {
                    ContentType = "text/html",
                    Body = "<h2>Payment Availability</h2><script>fetch('/PaymentAvailability/GetSummaryPaymentAvailability');</script>",
                });
            }
        });
        var workflowPage = new GeneratedWorkflowPage(Page)
        {
            ApiCallTimeoutMs = 500,
            SummaryPaymentAvailabilityTimeoutMs = 6000,
        };
        workflowPage.WatchApiCalls("/PaymentAvailability/GetSummaryPaymentAvailability");
        await workflowPage.GoToAsync(origin + "/PaymentAvailability/PaymentAvailabilityIndex");

        Assert.That(await workflowPage.CaptureWatchedApiResponseStatusAsync(), Is.EqualTo(200));
    }

    [Test]
    public async Task VerifyGridFeatureFiltersEachColumnAndOpensTheNextPageOfTheGridUnderTheHeading()
    {
        await Page.SetContentAsync(BuildGridFeaturePage(filtersWork: true));
        var workflowPage = new GeneratedWorkflowPage(Page);

        await workflowPage.VerifyGridFeatureAsync(
            "Payment Availability",
            new[] { "Root Name", "Site Name", "Segment Name" },
            verifyPagination: true);

        Assert.That(await Page.GetAttributeAsync("#grid", "data-automation-grid"), Is.Not.Null);
        Assert.That(await Page.GetAttributeAsync("#SummaryTablePayment", "data-automation-grid"), Is.Null);
        Assert.That(await Page.EvaluateAsync<int>("() => document.getElementById('grid').widget.dataSource.page()"), Is.EqualTo(2));
        Assert.That(await Page.EvaluateAsync<int>("() => document.getElementById('grid').widget.dataSource.filterCount()"), Is.Zero,
            "Each column filter is cleared after it is checked.");
        var evidence = await Page.Locator("#automation-grid-feature-evidence").InnerTextAsync();
        Assert.That(evidence, Does.Contain("first grid after the 'Payment Availability' heading"));
        Assert.That(evidence, Does.Contain("Filter 'Root Name' contains 'Root 0'"));
        Assert.That(evidence, Does.Contain("Filter 'Site Name' contains 'Site 0'"));
        Assert.That(evidence, Does.Contain("Filter 'Segment Name' contains 'Segment 0'"));
        Assert.That(evidence, Does.Contain("moved from page 1 to page 2"));
    }

    [Test]
    public async Task VerifyGridFeatureUsesTheGridUnderTheSummaryTableHeading()
    {
        await Page.SetContentAsync(BuildGridFeaturePage(filtersWork: true));

        await new GeneratedWorkflowPage(Page).VerifyGridFeatureAsync(
            "Summary Table",
            new[] { "Root Name" },
            verifyPagination: true);

        Assert.That(await Page.GetAttributeAsync("#SummaryTablePayment", "data-automation-grid"), Is.Not.Null);
        Assert.That(await Page.EvaluateAsync<int>("() => document.getElementById('SummaryTablePayment').widget.dataSource.page()"), Is.EqualTo(2));
    }

    [Test]
    public async Task VerifyGridFeatureWaitsLongerForSummaryLoadingFilteringClearingAndPagination()
    {
        await Page.SetContentAsync(BuildGridFeaturePage(filtersWork: true, readDelayMs: 2500));
        var workflowPage = new GeneratedWorkflowPage(Page)
        {
            DataSettleTimeoutMs = 2000,
            GridFilterClearTimeoutMs = 1000,
            SummaryPaymentAvailabilityTimeoutMs = 6000,
        };

        await workflowPage.VerifyGridFeatureAsync("Summary Table", new[] { "Root Name" }, verifyPagination: true);

        Assert.That(await Page.EvaluateAsync<int>("() => document.getElementById('SummaryTablePayment').widget.dataSource.page()"), Is.EqualTo(2));
        Assert.That(await Page.EvaluateAsync<int>("() => document.getElementById('SummaryTablePayment').widget.dataSource.filterCount()"), Is.Zero);
    }

    [Test]
    public async Task VerifyGridFeatureFailsWhenAColumnFilterDoesNotFilterTheGrid()
    {
        await Page.SetContentAsync(BuildGridFeaturePage(filtersWork: false));
        var workflowPage = new GeneratedWorkflowPage(Page) { DataSettleTimeoutMs = 3000 };

        var exception = Assert.ThrowsAsync<InvalidOperationException>(() => workflowPage.VerifyGridFeatureAsync(
            "Payment Availability",
            new[] { "Root Name" },
            verifyPagination: false));
        Assert.That(exception!.Message, Does.Contain("typing 'Root 0' in the 'Root Name' filter did not filter the grid"));
    }

    [Test]
    public async Task VerifyGridFeatureFailsClearlyWhenTheGridHasNoRecords()
    {
        await Page.SetContentAsync(BuildGridFeaturePage(filtersWork: true, recordCount: 0));
        var workflowPage = new GeneratedWorkflowPage(Page) { DataSettleTimeoutMs = 3000 };

        var exception = Assert.ThrowsAsync<InvalidOperationException>(() => workflowPage.VerifyGridFeatureAsync(
            "Payment Availability",
            new[] { "Root Name" },
            verifyPagination: true));
        Assert.That(exception!.Message, Does.Contain("'Payment Availability' grid (#grid) showed no records"));
    }

    // Two Kendo-like grids with a filter row (change on blur, server-style reload) and a pager, as on Payment Availability.
    private static string BuildGridFeaturePage(bool filtersWork, int recordCount = 120, int readDelayMs = 300)
    {
        const string gridMarkup = """
            <div class='k-grid' id='GRID_ID'>
              <table>
                <thead>
                  <tr><th data-field='RootName' data-title='Root Name'>Root Name</th><th data-field='SiteName' data-title='Site Name'>Site Name</th><th data-field='SegmentName' data-title='Segment Name'>Segment Name</th></tr>
                  <tr class='k-filter-row'>
                    <th><span data-field='RootName'><input type='text'></span></th>
                    <th><span data-field='SiteName'><input type='text'></span></th>
                    <th><input type='text'></th>
                  </tr>
                </thead>
                <tbody></tbody>
              </table>
              <div class='k-pager-wrap'><a href='#' title='Go to the next page'>&rsaquo;</a> <span class='k-pager-info'></span></div>
            </div>
            """;
        return "<h2>Payment Availability</h2>" + gridMarkup.Replace("GRID_ID", "grid")
            + "<h3>Summary Table</h3>" + gridMarkup.Replace("GRID_ID", "SummaryTablePayment")
            + """
            <script>
              window.jQuery = element => element;
              window.kendo = { widgetInstance: element => element && element.widget };
              const records = Array.from({ length: RECORD_COUNT }, (_, i) =>
                ({ RootName: `Root ${i % 3}`, SiteName: `Site ${i % 5}`, SegmentName: `Segment ${i % 7}` }));
              for (const grid of document.querySelectorAll('.k-grid')) {
                let filters = [];
                let page = 1;
                let shown = [];
                const matching = () => records.filter(record => filters.every(f => record[f.field].includes(f.value)));
                const dataSource = {
                  _requestInProgress: false,
                  view: () => shown,
                  total: () => matching().length,
                  pageSize: () => 50,
                  page: () => page,
                  filter: () => filters.length ? { logic: 'and', filters } : undefined,
                  filterCount: () => filters.length,
                  read() {
                    this._requestInProgress = true;
                    setTimeout(() => {
                      shown = matching().slice((page - 1) * 50, page * 50);
                      grid.querySelector('tbody').innerHTML = shown
                        .map(r => `<tr><td>${r.RootName}</td><td>${r.SiteName}</td><td>${r.SegmentName}</td></tr>`).join('');
                      grid.querySelector('.k-pager-info').textContent = `${shown.length} of ${matching().length} items`;
                      this._requestInProgress = false;
                    }, READ_DELAY_MS);
                  },
                };
                grid.widget = { dataSource };
                const fields = ['RootName', 'SiteName', 'SegmentName'];
                grid.querySelectorAll('.k-filter-row input').forEach((input, index) => input.addEventListener('change', () => {
                  if (!FILTERS_WORK) return;
                  filters = filters.filter(f => f.field !== fields[index]);
                  if (input.value) filters.push({ field: fields[index], operator: 'contains', value: input.value });
                  page = 1;
                  dataSource.read();
                }));
                grid.querySelector('[title="Go to the next page"]').addEventListener('click', event => {
                  event.preventDefault();
                  page++;
                  dataSource.read();
                });
                dataSource.read();
              }
            </script>
            """
            .Replace("RECORD_COUNT", recordCount.ToString())
            .Replace("READ_DELAY_MS", readDelayMs.ToString())
            .Replace("FILTERS_WORK", filtersWork ? "true" : "false");
    }

    private sealed record LocalHttpRequest(string Method, string Path, Dictionary<string, string> Headers, string Body);

    // Minimal HTTP server for checks that send requests outside the browser (Playwright routes only see browser traffic).
    private sealed class LocalHttpServer : IDisposable
    {
        private readonly System.Net.Sockets.TcpListener _listener = new(System.Net.IPAddress.Loopback, 0);
        private readonly CancellationTokenSource _stop = new();
        private readonly Func<LocalHttpRequest, (int Status, string ContentType, string Body, string? SetCookie)> _handler;
        private readonly List<LocalHttpRequest> _requests = new();

        public LocalHttpServer(Func<LocalHttpRequest, (int Status, string ContentType, string Body, string? SetCookie)> handler)
        {
            _handler = handler;
            _listener.Start();
            _ = Task.Run(AcceptLoopAsync);
        }

        public IReadOnlyList<LocalHttpRequest> Requests
        {
            get
            {
                lock (_requests)
                {
                    return _requests.ToArray();
                }
            }
        }

        public string Url(string path) => $"http://127.0.0.1:{((System.Net.IPEndPoint)_listener.LocalEndpoint).Port}{path}";

        private async Task AcceptLoopAsync()
        {
            while (!_stop.IsCancellationRequested)
            {
                System.Net.Sockets.TcpClient client;
                try
                {
                    client = await _listener.AcceptTcpClientAsync(_stop.Token);
                }
                catch (Exception)
                {
                    return;
                }

                _ = Task.Run(() => HandleAsync(client));
            }
        }

        private async Task HandleAsync(System.Net.Sockets.TcpClient client)
        {
            using (client)
            {
                var stream = client.GetStream();
                var buffer = new List<byte>();
                var chunk = new byte[8192];
                int headerEnd;
                while ((headerEnd = IndexOfHeaderEnd(buffer)) < 0)
                {
                    var read = await stream.ReadAsync(chunk);
                    if (read == 0) return;
                    buffer.AddRange(chunk.AsSpan(0, read).ToArray());
                }

                var headerLines = System.Text.Encoding.ASCII.GetString(buffer.ToArray(), 0, headerEnd).Split("\r\n");
                var requestLine = headerLines[0].Split(' ');
                var headers = headerLines.Skip(1)
                    .Select(line => line.Split(':', 2))
                    .Where(parts => parts.Length == 2)
                    .GroupBy(parts => parts[0].Trim().ToLowerInvariant())
                    .ToDictionary(group => group.Key, group => string.Join("; ", group.Select(parts => parts[1].Trim())));
                var contentLength = headers.TryGetValue("content-length", out var length) ? int.Parse(length) : 0;
                while (buffer.Count - headerEnd - 4 < contentLength)
                {
                    var read = await stream.ReadAsync(chunk);
                    if (read == 0) break;
                    buffer.AddRange(chunk.AsSpan(0, read).ToArray());
                }

                var body = System.Text.Encoding.UTF8.GetString(buffer.ToArray(), headerEnd + 4, Math.Max(0, buffer.Count - headerEnd - 4));
                var request = new LocalHttpRequest(requestLine[0], requestLine[1].Split('?')[0], headers, body);
                lock (_requests)
                {
                    _requests.Add(request);
                }

                var (status, contentType, responseBody, setCookie) = _handler(request);
                var bytes = System.Text.Encoding.UTF8.GetBytes(responseBody);
                var head = $"HTTP/1.1 {status} {(status == 200 ? "OK" : "Error")}\r\nContent-Type: {contentType}\r\n" +
                    $"Content-Length: {bytes.Length}\r\nConnection: close\r\n" +
                    (setCookie is null ? string.Empty : $"Set-Cookie: {setCookie}\r\n") + "\r\n";
                await stream.WriteAsync(System.Text.Encoding.ASCII.GetBytes(head));
                await stream.WriteAsync(bytes);
            }
        }

        private static int IndexOfHeaderEnd(List<byte> buffer)
        {
            for (var index = 0; index + 3 < buffer.Count; index++)
            {
                if (buffer[index] == '\r' && buffer[index + 1] == '\n' && buffer[index + 2] == '\r' && buffer[index + 3] == '\n')
                {
                    return index;
                }
            }

            return -1;
        }

        public void Dispose()
        {
            _stop.Cancel();
            _listener.Stop();
        }
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
