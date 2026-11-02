using Microsoft.Playwright;
using NUnit.Framework;
using QA.Regression.Automation.Pages;
using QA.Regression.Automation.Utilities;

namespace QA.Regression.Automation.Tests;

[TestFixture]
public class GeneratedWorkflowPageBrowserTests : BaseTest
{
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
        }
        else
        {
            Assert.ThrowsAsync<AssertionException>(async () =>
            {
                using var isolatedContext = new NUnit.Framework.Internal.TestExecutionContext.IsolatedContext();
                await workflowPage.ClickButtonAsync("Export to Excel");
            });
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
