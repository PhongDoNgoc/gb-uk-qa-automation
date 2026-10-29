using System.Text;
using Microsoft.Playwright;
using NUnit.Framework;
using QA.Regression.Automation.Pages;
using QA.Regression.Automation.Utilities;

namespace QA.Regression.Automation.Tests;

[TestFixture]
public class LoginPageTests : BaseTest
{
    [Test]
    public async Task GoToAsyncRetriesTransientConnectionClosure()
    {
        var navigationCount = 0;
        await Page.RouteAsync("https://login.example.test/**", async route =>
        {
            navigationCount++;
            if (navigationCount == 1)
            {
                await route.AbortAsync("connectionclosed");
                return;
            }

            await route.FulfillAsync(new RouteFulfillOptions
            {
                ContentType = "text/html",
                Body = "<html><body>login ready</body></html>",
            });
        });

        var loginPage = new LoginPage(Page);
        await loginPage.GoToAsync("https://login.example.test/");

        Assert.That(navigationCount, Is.EqualTo(2));
        Assert.That(await Page.GetByText("login ready").IsVisibleAsync(), Is.True);
    }

    [Test]
    public async Task LoginAsyncSubmitsWhenAnOverlayCoversTheSignInButton()
    {
        const string html = """
            <form id="localAccountForm">
                <input type="email" name="email">
                <input type="password" name="password">
                <button id="next" type="submit">Sign in</button>
            </form>
            <div style="position:fixed;inset:0;z-index:9999;background:transparent"></div>
            <script>
                document.getElementById('localAccountForm').addEventListener('submit', event => {
                    event.preventDefault();
                    document.body.dataset.submitted = 'true';
                });
            </script>
            """;
        var dataUrl = $"data:text/html;base64,{Convert.ToBase64String(Encoding.UTF8.GetBytes(html))}";
        await Page.GotoAsync(dataUrl);

        var loginPage = new LoginPage(Page);
        await loginPage.LoginAsync("user@example.test", "password");

        Assert.That(await Page.Locator("body").GetAttributeAsync("data-submitted"), Is.EqualTo("true"));
    }
}
