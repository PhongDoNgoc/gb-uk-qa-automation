using Microsoft.Playwright;
using NUnit.Framework;

namespace QA.Regression.Automation.Pages;

public class LoginPage
{
    private const int DefaultTimeoutMs = 30000;
    private const int PostLoginTimeoutMs = 90000;
    private const int NavigationAttempts = 3;
    private readonly IPage _page;

    private ILocator EmailInput => _page.Locator("input[type='email'], input[name='email'], input[autocomplete='username'], input[placeholder*='email' i]");
    private ILocator PasswordInput => _page.Locator("input[type='password'], input[name='password'], input[autocomplete='current-password'], input[placeholder*='password' i]");
    private ILocator SignInButton => _page.Locator("button:has-text('Sign in'), input[type='submit'], [role='button']:has-text('Sign in')");
    private ILocator WelcomeMessage => _page.GetByText("Welcome to your ViewPoint energy portal", new PageGetByTextOptions { Exact = false });

    public LoginPage(IPage page)
    {
        _page = page;
    }

    public async Task GoToAsync(string url)
    {
        for (var attempt = 1; attempt <= NavigationAttempts; attempt++)
        {
            try
            {
                await _page.GotoAsync(url, new PageGotoOptions
                {
                    WaitUntil = WaitUntilState.DOMContentLoaded,
                    Timeout = 60000,
                });
                return;
            }
            catch (PlaywrightException exception) when (
                attempt < NavigationAttempts && IsTransientConnectionFailure(exception))
            {
                TestContext.Progress.WriteLine(
                    $"Login page navigation failed with a transient connection error (attempt {attempt}/{NavigationAttempts}); retrying.");
                await Task.Delay(TimeSpan.FromSeconds(attempt));
            }
        }
    }

    internal static bool IsTransientConnectionFailure(PlaywrightException exception)
    {
        return exception.Message.Contains("net::ERR_CONNECTION_CLOSED", StringComparison.OrdinalIgnoreCase)
            || exception.Message.Contains("net::ERR_CONNECTION_RESET", StringComparison.OrdinalIgnoreCase);
    }

    public async Task<bool> IsLoginScreenDisplayedAsync()
    {
        await EmailInput.First.WaitForAsync(new LocatorWaitForOptions { Timeout = DefaultTimeoutMs });
        await PasswordInput.First.WaitForAsync(new LocatorWaitForOptions { Timeout = DefaultTimeoutMs });
        await SignInButton.First.WaitForAsync(new LocatorWaitForOptions { Timeout = DefaultTimeoutMs });
        return await EmailInput.First.IsVisibleAsync()
            && await PasswordInput.First.IsVisibleAsync()
            && await SignInButton.First.IsVisibleAsync();
    }

    public async Task LoginAsync(string username, string password)
    {
        await EmailInput.First.WaitForAsync(new LocatorWaitForOptions { Timeout = DefaultTimeoutMs });
        await EmailInput.First.FillAsync(username);
        await PasswordInput.First.WaitForAsync(new LocatorWaitForOptions { Timeout = DefaultTimeoutMs });
        await PasswordInput.First.FillAsync(password);
        await SignInButton.First.WaitForAsync(new LocatorWaitForOptions { Timeout = DefaultTimeoutMs });
        await SignInButton.First.PressAsync("Enter");
    }

    public async Task<bool> IsWelcomeMessageDisplayedAsync()
    {
        await WelcomeMessage.First.WaitForAsync(new LocatorWaitForOptions { Timeout = PostLoginTimeoutMs });
        return await WelcomeMessage.First.IsVisibleAsync();
    }

    public async Task<string> GetWelcomeMessageTextAsync()
    {
        await WelcomeMessage.First.WaitForAsync(new LocatorWaitForOptions { Timeout = PostLoginTimeoutMs });
        return (await WelcomeMessage.First.InnerTextAsync()).Trim();
    }

    public async Task<string> GetLoginErrorTextAsync(string expectedText)
    {
        var errorMessage = _page.GetByText(expectedText, new PageGetByTextOptions { Exact = false }).First;
        await errorMessage.WaitForAsync(new LocatorWaitForOptions { Timeout = DefaultTimeoutMs });
        return (await errorMessage.InnerTextAsync()).Trim();
    }
}
