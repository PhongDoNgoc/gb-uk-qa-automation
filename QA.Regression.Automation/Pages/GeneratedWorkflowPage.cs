using Microsoft.Playwright;

namespace QA.Regression.Automation.Pages;

public class GeneratedWorkflowPage
{
    private readonly IPage _page;

    public GeneratedWorkflowPage(IPage page)
    {
        _page = page;
    }

    public async Task GoToAsync(string url)
    {
        await _page.GotoAsync(url, new PageGotoOptions
        {
            WaitUntil = WaitUntilState.NetworkIdle,
            Timeout = 60000,
        });
    }

    public async Task<int> GoToAndCaptureApiResponseStatusAsync(string pageUrl, string apiPathFragment)
    {
        if (string.IsNullOrWhiteSpace(apiPathFragment))
        {
            throw new ArgumentException("API path fragment must be provided.", nameof(apiPathFragment));
        }

        await GoToAsync(pageUrl);
        var normalizedApiPath = NormalizeApiPathFragment(apiPathFragment);
        return await _page.EvaluateAsync<int>(
            @"async (apiUrl) => {
                const response = await fetch(apiUrl, { credentials: 'include' });
                return response.status;
            }",
            normalizedApiPath
        );
    }

    public async Task FillCredentialInputsAsync(string username, string password)
    {
        var emailInput = _page.Locator("input[type='email'], input[name='email'], input[autocomplete='username'], input[placeholder*='email' i]");
        var passwordInput = _page.Locator("input[type='password'], input[name='password'], input[autocomplete='current-password'], input[placeholder*='password' i]");

        await emailInput.First.WaitForAsync(new LocatorWaitForOptions { Timeout = 30000 });
        await emailInput.First.FillAsync(username);
        await passwordInput.First.WaitForAsync(new LocatorWaitForOptions { Timeout = 30000 });
        await passwordInput.First.FillAsync(password);
    }

    public async Task ClickButtonAsync(string buttonText)
    {
        var locator = _page.Locator(
            $"button:has-text('{buttonText}'), input[type='submit'][value='{buttonText}'], [role='button']:has-text('{buttonText}')"
        );

        await locator.First.WaitForAsync(new LocatorWaitForOptions { Timeout = 30000 });
        await locator.First.ClickAsync();
    }

    public async Task AssertTextVisibleAsync(string text)
    {
        var locator = _page.GetByText(text, new PageGetByTextOptions { Exact = false });
        await locator.First.WaitForAsync(new LocatorWaitForOptions { Timeout = 30000 });
    }

    private static string NormalizeApiPathFragment(string apiPathFragment)
    {
        var normalized = apiPathFragment.Trim();
        if (!normalized.StartsWith("/"))
        {
            normalized = $"/{normalized}";
        }

        return normalized;
    }
}
