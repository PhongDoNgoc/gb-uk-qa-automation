using Microsoft.Playwright;
using NUnit.Framework;
using QA.Regression.Automation.Pages;
using QA.Regression.Automation.Utilities;

namespace QA.Regression.Automation.Tests;

[TestFixture]
public class GeneratedWorkflowPageBrowserTests : BaseTest
{
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
