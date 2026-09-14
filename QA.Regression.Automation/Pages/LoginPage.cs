using Microsoft.Playwright;

namespace QA.Regression.Automation.Pages;

public class LoginPage
{
    private const int DefaultTimeoutMs = 30000;
    private const int PostLoginTimeoutMs = 90000;
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
        await _page.GotoAsync(url, new PageGotoOptions { WaitUntil = WaitUntilState.NetworkIdle, Timeout = 60000 });
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
        await SignInButton.First.ClickAsync();
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
}
