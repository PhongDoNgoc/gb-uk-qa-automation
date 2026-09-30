using Microsoft.Playwright;
using System.Text.Json;

namespace QA.Regression.Automation.Pages;

public class GeneratedWorkflowPage
{
    private readonly IPage _page;
    private const int ApiEvidencePreviewLength = 1600;

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
        var captureJson = await _page.EvaluateAsync<string>(
            @"async (apiUrl) => {
                const response = await fetch(apiUrl, { credentials: 'include' });
                const body = await response.text();
                return JSON.stringify({
                    statusCode: response.status,
                    requestUrl: response.url,
                    responseBody: body
                });
            }",
            normalizedApiPath
        );

        var capture = JsonSerializer.Deserialize<ApiResponseCapture>(captureJson)
            ?? throw new InvalidOperationException("Unable to deserialize API response capture.");
        await RenderApiEvidencePanelAsync(capture);
        return capture.StatusCode;
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

    private async Task RenderApiEvidencePanelAsync(ApiResponseCapture capture)
    {
        var responsePreview = BuildResponsePreview(capture.ResponseBody);
        await _page.EvaluateAsync(
            @"({ requestUrl, statusCode, responsePreview }) => {
                const panelId = 'copilot-api-evidence-panel';
                let panel = document.getElementById(panelId);
                if (!panel) {
                    panel = document.createElement('div');
                    panel.id = panelId;
                    panel.style.position = 'fixed';
                    panel.style.top = '12px';
                    panel.style.right = '12px';
                    panel.style.width = '420px';
                    panel.style.maxHeight = '70vh';
                    panel.style.overflow = 'auto';
                    panel.style.zIndex = '2147483647';
                    panel.style.background = 'rgba(255,255,255,0.98)';
                    panel.style.border = '2px solid #2563eb';
                    panel.style.borderRadius = '8px';
                    panel.style.boxShadow = '0 8px 24px rgba(0, 0, 0, 0.18)';
                    panel.style.padding = '12px';
                    panel.style.fontFamily = 'Consolas, Menlo, Monaco, monospace';
                    panel.style.fontSize = '12px';
                    panel.style.color = '#111827';
                    document.body.appendChild(panel);
                }

                panel.innerHTML = '';

                const title = document.createElement('div');
                title.textContent = 'API evidence';
                title.style.fontWeight = '700';
                title.style.fontSize = '14px';
                title.style.marginBottom = '8px';
                panel.appendChild(title);

                const status = document.createElement('div');
                status.textContent = `Status: ${statusCode}`;
                status.style.fontWeight = '700';
                status.style.color = statusCode >= 200 && statusCode < 400 ? '#166534' : '#b91c1c';
                status.style.marginBottom = '8px';
                panel.appendChild(status);

                const requestLabel = document.createElement('div');
                requestLabel.textContent = 'Request URL:';
                requestLabel.style.fontWeight = '600';
                requestLabel.style.marginBottom = '4px';
                panel.appendChild(requestLabel);

                const requestValue = document.createElement('pre');
                requestValue.textContent = requestUrl;
                requestValue.style.whiteSpace = 'pre-wrap';
                requestValue.style.wordBreak = 'break-word';
                requestValue.style.margin = '0 0 10px 0';
                panel.appendChild(requestValue);

                const bodyLabel = document.createElement('div');
                bodyLabel.textContent = 'Response preview:';
                bodyLabel.style.fontWeight = '600';
                bodyLabel.style.marginBottom = '4px';
                panel.appendChild(bodyLabel);

                const bodyValue = document.createElement('pre');
                bodyValue.textContent = responsePreview;
                bodyValue.style.whiteSpace = 'pre-wrap';
                bodyValue.style.wordBreak = 'break-word';
                bodyValue.style.margin = '0';
                panel.appendChild(bodyValue);
            }",
            new
            {
                capture.RequestUrl,
                capture.StatusCode,
                responsePreview,
            }
        );
    }

    private static string BuildResponsePreview(string responseBody)
    {
        if (string.IsNullOrWhiteSpace(responseBody))
        {
            return "<empty response body>";
        }

        var trimmed = responseBody.Trim();
        if (trimmed.Length > ApiEvidencePreviewLength)
        {
            trimmed = $"{trimmed[..ApiEvidencePreviewLength]}\n... (truncated)";
        }

        try
        {
            using var document = JsonDocument.Parse(trimmed);
            return JsonSerializer.Serialize(document.RootElement, new JsonSerializerOptions
            {
                WriteIndented = true,
            });
        }
        catch (JsonException)
        {
            return trimmed;
        }
    }

    private sealed record ApiResponseCapture(int StatusCode, string RequestUrl, string ResponseBody);
}
