using System.Collections.Generic;
using Microsoft.Playwright;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using NUnit.Framework;

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
        var targetUri = new Uri(url, UriKind.Absolute);
        var isSameOrigin = Uri.TryCreate(_page.Url, UriKind.Absolute, out var currentUri)
            && currentUri.GetLeftPart(UriPartial.Authority).Equals(
                targetUri.GetLeftPart(UriPartial.Authority),
                StringComparison.OrdinalIgnoreCase);
        var navigationItem = isSameOrigin ? GetNavigationItem(targetUri.AbsolutePath) : null;
        if (navigationItem is not null)
        {
            await NavigateThroughUtilitiesAsync(targetUri, navigationItem);
        }
        else
        {
            await _page.GotoAsync(url, new PageGotoOptions
            {
                WaitUntil = WaitUntilState.NetworkIdle,
                Timeout = 60000,
            });
        }

        await WaitForPageReadyAsync(navigationItem);
    }

    public async Task<int> GoToAndCaptureApiResponseStatusAsync(string pageUrl, string apiPathFragment)
    {
        if (string.IsNullOrWhiteSpace(apiPathFragment))
        {
            throw new ArgumentException("API path fragment must be provided.", nameof(apiPathFragment));
        }

        await GoToAsync(pageUrl);
        var normalizedApiPath = NormalizeApiPathFragment(apiPathFragment);
        var capture = await FetchApiResponseWithBrowserCookiesAsync(pageUrl, normalizedApiPath);
        await RenderApiEvidencePanelAsync(capture);
        await AttachApiEvidenceScreenshotAsync();
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
        if (buttonText.Equals("Refresh", StringComparison.OrdinalIgnoreCase))
        {
            var refreshControl = GetRefreshControlLocator();

            try
            {
                await refreshControl.WaitForAsync(new LocatorWaitForOptions
                {
                    State = WaitForSelectorState.Visible,
                    Timeout = 60000,
                });
            }
            catch (TimeoutException)
            {
                throw new TimeoutException(
                    $"Timeout 60000ms exceeded while waiting for a visible Refresh control on page '{_page.Url}'."
                );
            }

            await refreshControl.ScrollIntoViewIfNeededAsync();
            await refreshControl.ClickAsync(new LocatorClickOptions { Timeout = 60000 });
            return;
        }

        var locators = new List<ILocator>();

        locators.AddRange(new[]
        {
            _page.GetByRole(AriaRole.Button, new PageGetByRoleOptions { Name = buttonText, Exact = false }),
            _page.Locator(
                $"button:has-text('{buttonText}'), input[type='submit'][value='{buttonText}'], input[type='button'][value='{buttonText}'], [role='button']:has-text('{buttonText}')"
            ),
            _page.Locator(
                $"[aria-label*='{buttonText}' i], [title*='{buttonText}' i], input[type='submit'][value*='{buttonText}' i], input[type='button'][value*='{buttonText}' i]"
            ),
        });

        foreach (var locator in locators)
        {
            try
            {
                await locator.First.WaitForAsync(new LocatorWaitForOptions
                {
                    State = WaitForSelectorState.Visible,
                    Timeout = 10000,
                });
                await locator.First.ScrollIntoViewIfNeededAsync();
                await locator.First.ClickAsync();
                return;
            }
            catch (TimeoutException)
            {
            }
        }

        throw new TimeoutException(
            $"Timeout 30000ms exceeded while waiting for a clickable control matching '{buttonText}' on page '{_page.Url}'."
        );
    }

    internal static string? GetNavigationItem(string path)
    {
        var normalizedPath = path.TrimEnd('/');
        if (normalizedPath.Equals("/UnitDetails/UnitDetail", StringComparison.OrdinalIgnoreCase))
        {
            return "Unit Details";
        }

        return null;
    }

    private async Task NavigateThroughUtilitiesAsync(Uri targetUri, string navigationItem)
    {
        if (PathsMatch(new Uri(_page.Url).AbsolutePath, targetUri.AbsolutePath))
        {
            return;
        }

        var targetLink = _page.GetByRole(
            AriaRole.Link,
            new PageGetByRoleOptions { Name = navigationItem, Exact = true });

        if (!await targetLink.IsVisibleAsync())
        {
            var utilitiesMenu = _page.GetByText("Utilities", new PageGetByTextOptions { Exact = true }).First;
            await utilitiesMenu.WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Visible,
                Timeout = 30000,
            });
            await utilitiesMenu.ClickAsync();
        }

        await targetLink.WaitForAsync(new LocatorWaitForOptions
        {
            State = WaitForSelectorState.Visible,
            Timeout = 30000,
        });
        await targetLink.ClickAsync();
        await _page.WaitForLoadStateAsync(
            LoadState.NetworkIdle,
            new PageWaitForLoadStateOptions { Timeout = 60000 });

        if (!PathsMatch(new Uri(_page.Url).AbsolutePath, targetUri.AbsolutePath))
        {
            throw new InvalidOperationException(
                $"Selecting '{navigationItem}' navigated to '{_page.Url}' instead of '{targetUri.AbsolutePath}'.");
        }
    }

    private async Task WaitForPageReadyAsync(string? navigationItem)
    {
        if (navigationItem is null)
        {
            return;
        }

        var heading = _page.GetByRole(
            AriaRole.Heading,
            new PageGetByRoleOptions { Name = navigationItem, Exact = true }).First;
        await heading.WaitForAsync(new LocatorWaitForOptions
        {
            State = WaitForSelectorState.Visible,
            Timeout = 60000,
        });

        if (navigationItem.Equals("Unit Details", StringComparison.Ordinal))
        {
            var exportControl = _page.Locator(
                "button:has-text('Export to Excel'), a:has-text('Export to Excel'), " +
                "[role='button']:has-text('Export to Excel')");
            await exportControl.First.WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Visible,
                Timeout = 90000,
            });

            await GetRefreshControlLocator().WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Visible,
                Timeout = 90000,
            });

            var gridRow = _page.Locator(
                "table tbody tr, [role='grid'] [role='row'], .k-grid tbody tr");
            await gridRow.First.WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Visible,
                Timeout = 90000,
            });
        }

        await _page.WaitForLoadStateAsync(
            LoadState.NetworkIdle,
            new PageWaitForLoadStateOptions { Timeout = 60000 });
    }

    private ILocator GetRefreshControlLocator()
    {
        var refreshSelector = string.Join(", ", new[]
        {
            "button:has([class*='refresh' i])",
            "button[class*='refresh' i]",
            "[role='button']:has([class*='refresh' i])",
            "[role='button'][class*='refresh' i]",
            "a:has([class*='refresh' i])",
            "a[class*='refresh' i]",
            "button:has([class*='sync' i])",
            "button[class*='sync' i]",
            "[role='button']:has([class*='sync' i])",
            "[role='button'][class*='sync' i]",
            "a:has([class*='sync' i])",
            "a[class*='sync' i]",
            "button:has([class*='reload' i])",
            "button[class*='reload' i]",
            "[role='button']:has([class*='reload' i])",
            "[role='button'][class*='reload' i]",
            "a:has([class*='reload' i])",
            "a[class*='reload' i]",
            "button:has([class*='rotate' i])",
            "button[class*='rotate' i]",
            "[role='button']:has([class*='rotate' i])",
            "[role='button'][class*='rotate' i]",
            "a:has([class*='rotate' i])",
            "a[class*='rotate' i]",
            "button:has([data-icon*='refresh' i])",
            "[role='button']:has([data-icon*='refresh' i])",
            "button:has-text('Refresh')",
            "input[type='submit'][value*='Refresh' i]",
            "input[type='button'][value*='Refresh' i]",
            "[role='button']:has-text('Refresh')",
            "a:has-text('Refresh')",
            "[aria-label*='Refresh' i]",
            "[title*='Refresh' i]",
            "[data-original-title*='refresh' i]",
        });
        return _page.Locator(refreshSelector).First;
    }

    private static bool PathsMatch(string actualPath, string expectedPath)
    {
        return actualPath.TrimEnd('/').Equals(expectedPath.TrimEnd('/'), StringComparison.OrdinalIgnoreCase);
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

    private async Task<ApiResponseCapture> FetchApiResponseWithBrowserCookiesAsync(string pageUrl, string apiPathFragment)
    {
        var requestUri = BuildRequestUri(pageUrl, apiPathFragment);
        var cookieContainer = new CookieContainer();
        var cookies = await _page.Context.CookiesAsync(new[] { requestUri.ToString() });

        foreach (var cookie in cookies)
        {
            var normalizedDomain = string.IsNullOrWhiteSpace(cookie.Domain)
                ? requestUri.Host
                : cookie.Domain.TrimStart('.');
            var normalizedPath = string.IsNullOrWhiteSpace(cookie.Path) ? "/" : cookie.Path;

            var netCookie = new System.Net.Cookie(cookie.Name, cookie.Value, normalizedPath, normalizedDomain)
            {
                Secure = cookie.Secure,
                HttpOnly = cookie.HttpOnly,
            };

            if (cookie.Expires > 0)
            {
                netCookie.Expires = DateTimeOffset.FromUnixTimeSeconds((long)cookie.Expires).UtcDateTime;
            }

            cookieContainer.Add(netCookie);
        }

        using var handler = new HttpClientHandler
        {
            CookieContainer = cookieContainer,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate | DecompressionMethods.Brotli,
        };
        using var client = new HttpClient(handler);
        client.DefaultRequestHeaders.Add("Accept", "application/json, text/plain, */*");
        using var response = await client.GetAsync(requestUri);
        var responseBody = await response.Content.ReadAsStringAsync();

        return new ApiResponseCapture(
            (int)response.StatusCode,
            requestUri.ToString(),
            responseBody
        );
    }

    internal static Uri BuildRequestUri(string pageUrl, string apiPathFragment)
    {
        if (!Uri.TryCreate(pageUrl, UriKind.Absolute, out var baseUri)
            || !IsHttpUri(baseUri))
        {
            throw new InvalidOperationException(
                $"Page URL '{pageUrl}' is not a valid absolute HTTP or HTTPS URI.");
        }

        var normalizedApiPath = apiPathFragment.Trim();
        if (normalizedApiPath.StartsWith("//", StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                $"API path '{apiPathFragment}' must not be a network-path reference.");
        }

        if (normalizedApiPath.StartsWith("/", StringComparison.Ordinal))
        {
            return new Uri(baseUri, normalizedApiPath);
        }

        if (Uri.TryCreate(normalizedApiPath, UriKind.Absolute, out var absoluteUri))
        {
            if (!IsHttpUri(absoluteUri))
            {
                throw new InvalidOperationException(
                    $"API URL '{apiPathFragment}' must use HTTP or HTTPS.");
            }

            return absoluteUri;
        }

        return new Uri(baseUri, normalizedApiPath);
    }

    private static bool IsHttpUri(Uri uri)
    {
        return uri.IsAbsoluteUri
            && !string.IsNullOrWhiteSpace(uri.Host)
            && (uri.Scheme.Equals(Uri.UriSchemeHttp, StringComparison.OrdinalIgnoreCase)
                || uri.Scheme.Equals(Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase));
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
                requestUrl = capture.RequestUrl,
                statusCode = capture.StatusCode,
                responsePreview = responsePreview,
            }
        );
    }

    private async Task AttachApiEvidenceScreenshotAsync()
    {
        var artifactDir = Path.Combine(TestContext.CurrentContext.WorkDirectory, "TestResults");
        Directory.CreateDirectory(artifactDir);

        var screenshotPath = Path.Combine(artifactDir, $"ApiEvidence-{Guid.NewGuid():N}.png");
        await _page.ScreenshotAsync(new PageScreenshotOptions
        {
            Path = screenshotPath,
            FullPage = true,
        });
        TestContext.AddTestAttachment(screenshotPath, "API response evidence");
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
