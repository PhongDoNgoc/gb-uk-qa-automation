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
    private const int ApiEvidenceReadinessTimeoutMs = 30000;
    private const int UnitDetailsReadinessTimeoutMs = 30000;
    private const int DataSettleStableMs = 1500;

    internal int ExportReadyTimeoutMs { get; init; } = 120000;
    internal int ExportDownloadTimeoutMs { get; init; } = 120000;
    internal int DataSettleTimeoutMs { get; init; } = 60000;
    internal int ApiCallTimeoutMs { get; init; } = 45000;
    internal int SelectorOptionsTimeoutMs { get; init; } = 30000;
    internal int DependentOptionsTimeoutMs { get; init; } = 90000;
    internal int PendingRequestIgnoreAfterMs { get; init; } = 30000;
    internal int GridFilterClearTimeoutMs { get; init; } = 15000;
    internal int SummaryPaymentAvailabilityTimeoutMs { get; init; } = 300000;
    private const int DataRequestQuietMs = 500;
    private const int ReapplySelectionIntervalMs = 5000;

    private readonly Dictionary<IRequest, DateTime> _pendingDataRequests = new();
    private (ILocator Control, string Label)? _lastNativeSelection;

    private readonly List<string> _appliedSelections = new();
    private int _selectionCount;
    private ApiCallWatch? _apiWatch;

    // Kendo's DataSource sets _requestInProgress while a read is queued or running; exporting while it is set
    // queues the all-pages export read behind the reload and the download never starts.
    private const string PageDataStateScript =
        """
        (exportToken) => {
            const isVisible = element => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                const bounds = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && bounds.width > 0 && bounds.height > 0;
            };
            const widgetOf = element => window.kendo && window.jQuery ? window.kendo.widgetInstance(window.jQuery(element)) : null;
            const isLoading = widget => !!(widget && widget.dataSource && widget.dataSource._requestInProgress);
            const exportControl = exportToken ? document.querySelector(`[data-automation-export="${exportToken}"]`) : null;
            const grids = exportControl
                ? [exportControl.closest('.k-grid')].filter(Boolean)
                : Array.from(document.querySelectorAll('.k-grid')).filter(grid =>
                    grid.querySelector('.k-grid-excel') || /export\s+to\s+excel/i.test(grid.querySelector('.k-grid-toolbar, .k-toolbar')?.textContent || ''));
            const busy = [];
            for (const grid of grids) {
                if (Array.from(grid.querySelectorAll('.k-loading-mask')).some(isVisible)) busy.push(`#${grid.id || 'grid'} loading mask visible`);
                if (isLoading(widgetOf(grid))) busy.push(`#${grid.id || 'grid'} data request in progress`);
            }
            for (const element of document.querySelectorAll('[data-role="dropdownlist"], [data-role="combobox"], [data-role="multiselect"], [data-role="dropdowntree"]')) {
                if (isLoading(widgetOf(element))) busy.push(`#${element.id || element.name || 'dropdown'} options loading`);
            }
            let disabled = null;
            if (exportControl) {
                const style = window.getComputedStyle(exportControl);
                if (!isVisible(exportControl)) disabled = 'not visible';
                else if (exportControl.disabled || exportControl.hasAttribute('disabled')) disabled = 'disabled attribute set';
                else if (exportControl.getAttribute('aria-disabled') === 'true') disabled = 'aria-disabled';
                else if (exportControl.matches('.k-disabled, .k-state-disabled, .disabled')) disabled = 'disabled class';
                else if (style.pointerEvents === 'none') disabled = 'pointer-events none';
                else if (parseFloat(style.opacity) < 0.9) disabled = `opacity ${style.opacity}`;
            }
            return { busy, disabled };
        }
        """;

    public GeneratedWorkflowPage(IPage page)
    {
        _page = page;
        _page.Request += (_, request) =>
        {
            if (IsDataRequest(request))
            {
                lock (_pendingDataRequests)
                {
                    _pendingDataRequests[request] = DateTime.UtcNow;
                }
            }
        };
        _page.RequestFinished += (_, request) => ForgetDataRequest(request);
        _page.RequestFailed += (_, request) => ForgetDataRequest(request);
    }

    private static bool IsDataRequest(IRequest request) =>
        request.ResourceType is "xhr" or "fetch";

    internal int ResolveApiTimeoutMs(string apiPath, int defaultTimeoutMs) =>
        apiPath.Split('?', '#')[0].TrimEnd('/').EndsWith(
            "/PaymentAvailability/GetSummaryPaymentAvailability", StringComparison.OrdinalIgnoreCase)
            ? SummaryPaymentAvailabilityTimeoutMs
            : defaultTimeoutMs;

    private void ForgetDataRequest(IRequest request)
    {
        lock (_pendingDataRequests)
        {
            _pendingDataRequests.Remove(request);
        }
    }

    // Waits until the page's own XHR/fetch calls (for example the lists that later fill dependent selectors)
    // have finished. Requests running longer than PendingRequestIgnoreAfterMs are treated as polling and ignored.
    private async Task WaitForPendingDataRequestsAsync(string reason)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(DataSettleTimeoutMs);
        DateTime? quietSince = null;
        while (true)
        {
            var now = DateTime.UtcNow;
            string[] pending;
            lock (_pendingDataRequests)
            {
                pending = _pendingDataRequests
                    .Where(entry => (now - entry.Value).TotalMilliseconds < PendingRequestIgnoreAfterMs)
                    .Select(entry => $"{entry.Key.Method} {entry.Key.Url}")
                    .ToArray();
            }

            if (pending.Length == 0)
            {
                quietSince ??= now;
                if ((now - quietSince.Value).TotalMilliseconds >= DataRequestQuietMs)
                {
                    return;
                }
            }
            else
            {
                quietSince = null;
            }

            if (now >= deadline)
            {
                TestContext.Progress.WriteLine(
                    $"Test {TestContext.CurrentContext.Test.Name}: page data requests were still running {reason} " +
                    $"after {DataSettleTimeoutMs} ms; continuing. Pending: {string.Join(", ", pending)}");
                return;
            }

            await Task.Delay(100);
        }
    }

    public async Task GoToAsync(string url, string? menuItem = null)
    {
        var targetUri = new Uri(url, UriKind.Absolute);
        var isSameOrigin = Uri.TryCreate(_page.Url, UriKind.Absolute, out var currentUri)
            && currentUri.GetLeftPart(UriPartial.Authority).Equals(
                targetUri.GetLeftPart(UriPartial.Authority),
                StringComparison.OrdinalIgnoreCase);
        var navigationItem = isSameOrigin ? GetNavigationItem(targetUri.AbsolutePath) : null;
        var unitDetailsDiagnostics = GetNavigationItem(targetUri.AbsolutePath) == "Unit Details"
            ? new UnitDetailsNavigationDiagnostics(_page)
            : null;

        try
        {
            if (navigationItem is not null)
            {
                await NavigateThroughUtilitiesAsync(targetUri, navigationItem);
            }
            else
            {
                var response = await _page.GotoAsync(url, new PageGotoOptions
                {
                    WaitUntil = WaitUntilState.DOMContentLoaded,
                    Timeout = 60000,
                });
                if (response is not null && response.Status >= 400)
                {
                    if (string.IsNullOrWhiteSpace(menuItem))
                    {
                        throw new InvalidOperationException(
                            $"Navigation to '{url}' returned HTTP {response.Status}. Check the URL in the Test Case steps.");
                    }

                    await NavigateThroughMenuLinkAsync(targetUri, menuItem, response.Status);
                }
            }

            await WaitForPageReadyAsync(
                navigationItem,
                isSameOrigin && IsCustomerDetailsPath(targetUri.AbsolutePath));
        }
        catch (TimeoutException exception) when (unitDetailsDiagnostics is not null)
        {
            throw new TimeoutException(
                $"{exception.Message} Browser diagnostics: {unitDetailsDiagnostics.GetSummary()}",
                exception);
        }
        finally
        {
            unitDetailsDiagnostics?.Dispose();
        }
    }

    public async Task<int> GoToAndCaptureApiResponseStatusAsync(string pageUrl, string apiPathFragment)
    {
        if (string.IsNullOrWhiteSpace(apiPathFragment))
        {
            throw new ArgumentException("API path fragment must be provided.", nameof(apiPathFragment));
        }

        await _page.GotoAsync(pageUrl, new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
            Timeout = 60000,
        });
        var normalizedApiPath = NormalizeApiPathFragment(apiPathFragment);
        var capture = await FetchApiResponseWithBrowserCookiesAsync(pageUrl, normalizedApiPath);
        await TryWaitForApiEvidencePageReadyAsync(pageUrl);
        await RenderApiEvidencePanelAsync(capture);
        await AttachApiEvidenceScreenshotAsync();
        return capture.StatusCode;
    }

    // Opens the page, then sends the Test Case's payload to the API as a form POST with the signed-in session,
    // the same way the page's grids call it.
    public async Task<int> GoToAndCaptureApiResponseStatusAsync(
        string pageUrl,
        string apiPathFragment,
        IReadOnlyList<KeyValuePair<string, string>> payload)
    {
        await _page.GotoAsync(pageUrl, new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
            Timeout = 60000,
        });
        return await CaptureApiResponseStatusAsync(apiPathFragment, payload);
    }

    // Sends the payload from the page that is currently open, for example after the Test Case's selections.
    public async Task<int> CaptureApiResponseStatusAsync(
        string apiPathFragment,
        IReadOnlyList<KeyValuePair<string, string>> payload)
    {
        if (string.IsNullOrWhiteSpace(apiPathFragment))
        {
            throw new ArgumentException("API path fragment must be provided.", nameof(apiPathFragment));
        }

        ArgumentNullException.ThrowIfNull(payload);
        var pageUrl = _page.Url;
        var capture = await FetchApiResponseWithBrowserCookiesAsync(pageUrl, NormalizeApiPathFragment(apiPathFragment), payload);
        TestContext.Progress.WriteLine(
            $"Test {TestContext.CurrentContext.Test.Name}: sent POST {capture.RequestUrl} with payload " +
            $"{capture.Payload} and received HTTP {capture.StatusCode}.");
        await TryWaitForApiEvidencePageReadyAsync(pageUrl);
        await RenderApiEvidencePanelAsync(capture);
        await AttachApiEvidenceScreenshotAsync();
        return capture.StatusCode;
    }

    // Records the page's own calls to the API so the check can use the call made after the Test Case's
    // selections. The page may send it with a method or body that a standalone GET cannot reproduce.
    public void WatchApiCalls(string apiPathFragment)
    {
        if (string.IsNullOrWhiteSpace(apiPathFragment))
        {
            throw new ArgumentException("API path fragment must be provided.", nameof(apiPathFragment));
        }

        StopWatchingApiCalls();
        var normalizedApiPath = NormalizeApiPathFragment(apiPathFragment);
        var watchedPath = Uri.TryCreate(apiPathFragment.Trim(), UriKind.Absolute, out var absoluteUri) && IsHttpUri(absoluteUri)
            ? absoluteUri.AbsolutePath
            : normalizedApiPath.Split('?', '#')[0];
        var watch = new ApiCallWatch(watchedPath.TrimEnd('/'));
        watch.Handler = (_, request) =>
        {
            if (Uri.TryCreate(request.Url, UriKind.Absolute, out var requestUri)
                && requestUri.AbsolutePath.TrimEnd('/').EndsWith(watch.Path, StringComparison.OrdinalIgnoreCase))
            {
                lock (watch.Calls)
                {
                    watch.Calls.Add((request, Volatile.Read(ref _selectionCount)));
                }
            }
        };
        _page.Request += watch.Handler;
        _apiWatch = watch;
    }

    public async Task<int> CaptureWatchedApiResponseStatusAsync()
    {
        var watch = _apiWatch ?? throw new InvalidOperationException(
            "Call WatchApiCalls before CaptureWatchedApiResponseStatusAsync.");
        try
        {
            var selectionCount = Volatile.Read(ref _selectionCount);
            var selections = string.Join("; ", _appliedSelections);
            var timeoutMs = ResolveApiTimeoutMs(watch.Path, ApiCallTimeoutMs);
            var request = await WaitForWatchedCallAsync(watch, selectionCount, timeoutMs);
            if (request is null && selectionCount > 1)
            {
                request = LatestWatchedCall(watch, 1);
                if (request is not null)
                {
                    TestContext.Progress.WriteLine(
                        $"WARNING: Test {TestContext.CurrentContext.Test.Name}: the page did not call '{watch.Path}' again " +
                        $"within {timeoutMs} ms after the last selection; using the call made after an earlier selection ({selections}).");
                }
            }

            if (request is null)
            {
                int earlierCalls;
                lock (watch.Calls)
                {
                    earlierCalls = watch.Calls.Count;
                }

                var after = selectionCount > 0 ? $"after selecting {selections}" : "after opening the page";
                throw new InvalidOperationException(
                    $"The page did not call '{watch.Path}' within {timeoutMs} ms {after} on '{_page.Url}'. " +
                    $"Calls seen before that point: {earlierCalls}. Check the Test Case selections and API URL.");
            }

            var response = await request.ResponseAsync().WaitAsync(TimeSpan.FromMilliseconds(timeoutMs))
                ?? throw new InvalidOperationException(
                    $"The page's {request.Method} call to '{request.Url}' failed without a response: {request.Failure ?? "unknown error"}.");
            string responseBody;
            try
            {
                responseBody = await response.TextAsync();
            }
            catch (PlaywrightException exception)
            {
                responseBody = $"<response body unavailable: {exception.Message}>";
            }

            TestContext.Progress.WriteLine(
                $"Test {TestContext.CurrentContext.Test.Name}: page called {request.Method} {request.Url} " +
                $"{(selectionCount > 0 ? $"after selecting {selections} " : string.Empty)}and received HTTP {response.Status}.");

            await _page.WaitForTimeoutAsync(500);
            var capture = new ApiResponseCapture(
                response.Status,
                request.Url,
                responseBody,
                $"{request.Method} (sent by the page)",
                selectionCount > 0 ? selections : null);
            await RenderApiEvidencePanelAsync(capture);
            await AttachApiEvidenceScreenshotAsync();
            return capture.StatusCode;
        }
        finally
        {
            StopWatchingApiCalls();
        }
    }

    private static async Task<IRequest?> WaitForWatchedCallAsync(ApiCallWatch watch, int minimumSelectionCount, int timeoutMs)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        while (true)
        {
            var request = LatestWatchedCall(watch, minimumSelectionCount);
            if (request is not null || DateTime.UtcNow >= deadline)
            {
                return request;
            }

            await Task.Delay(250);
        }
    }

    private static IRequest? LatestWatchedCall(ApiCallWatch watch, int minimumSelectionCount)
    {
        lock (watch.Calls)
        {
            return watch.Calls.LastOrDefault(call => call.SelectionCount >= minimumSelectionCount).Request;
        }
    }

    private void StopWatchingApiCalls()
    {
        if (_apiWatch?.Handler is { } handler)
        {
            _page.Request -= handler;
        }

        _apiWatch = null;
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
        if (!buttonText.Equals("Export to Excel", StringComparison.OrdinalIgnoreCase))
        {
            await ClickControlAsync(buttonText);
            return;
        }

        var exportControl = _page.Locator(
                "button, a, [role='button'], input[type='button'], input[type='submit']")
            .Filter(new LocatorFilterOptions
            {
                Visible = true,
                HasTextRegex = new System.Text.RegularExpressions.Regex(
                    @"^\s*Export\s+to\s+Excel\s*$",
                    System.Text.RegularExpressions.RegexOptions.IgnoreCase),
            })
            .Or(_page.Locator(
                "a.k-grid-excel, button.k-grid-excel, " +
                "input[value='Export to Excel' i], " +
                "button[aria-label='Export to Excel' i], a[aria-label='Export to Excel' i]"))
            .Filter(new LocatorFilterOptions { Visible = true })
            .First;
        await exportControl.WaitForAsync(new LocatorWaitForOptions
        {
            State = WaitForSelectorState.Visible,
            Timeout = 60000,
        });
        await WaitForExportControlReadyAsync(exportControl);

        var downloadTask = _page.WaitForDownloadAsync(new PageWaitForDownloadOptions { Timeout = ExportDownloadTimeoutMs });
        await exportControl.ClickAsync(new LocatorClickOptions { Timeout = 60000 });
        TestContext.Progress.WriteLine(
            $"Test {TestContext.CurrentContext.Test.Name}: visible Export to Excel control clicked; waiting for download.");
        var download = await WaitForDownloadOrPageMessageAsync(downloadTask);
        var failure = await download.FailureAsync();
        Assert.That(failure, Is.Null, $"Excel export download failed: {failure}");

        var extension = Path.GetExtension(download.SuggestedFilename).ToLowerInvariant();
        Assert.That(extension, Is.AnyOf(".xls", ".xlsx"),
            $"Expected an Excel download, but received '{download.SuggestedFilename}'.");

        var artifactDir = Path.Combine(TestContext.CurrentContext.WorkDirectory, "TestResults");
        Directory.CreateDirectory(artifactDir);
        var downloadPath = Path.Combine(artifactDir, $"ExcelExport-{Guid.NewGuid():N}{extension}");
        await download.SaveAsAsync(downloadPath);
        var fileSize = new FileInfo(downloadPath).Length;
        Assert.That(fileSize, Is.GreaterThan(0),
            "The exported Excel file is empty.");
        TestContext.AddTestAttachment(downloadPath, $"Excel export: {download.SuggestedFilename}");
        await AttachExcelDownloadEvidenceAsync(download.SuggestedFilename, fileSize, artifactDir);
    }

    private async Task WaitForExportControlReadyAsync(ILocator exportControl)
    {
        var token = Guid.NewGuid().ToString("N");
        await exportControl.EvaluateAsync("(element, token) => element.setAttribute('data-automation-export', token)", token);
        var state = await WaitForPageDataSettledAsync(token, ExportReadyTimeoutMs);
        if (state.Settled)
        {
            return;
        }

        if (state.Busy.Length == 0 && state.Disabled is not null)
        {
            throw new InvalidOperationException(
                $"The Export to Excel control stayed unavailable ({state.Disabled}) for {ExportReadyTimeoutMs / 1000}s on page '{_page.Url}'. " +
                "The grid most likely has no data for the selected filters; check the Test Case selection data.");
        }

        throw new TimeoutException(
            $"The grid owning Export to Excel did not finish loading within {ExportReadyTimeoutMs / 1000}s on page '{_page.Url}' " +
            $"({string.Join("; ", state.Busy.Append(state.Disabled is null ? null : $"export control {state.Disabled}").OfType<string>())}).");
    }

    private async Task<(bool Settled, string[] Busy, string? Disabled)> WaitForPageDataSettledAsync(string? exportToken, int timeoutMs)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        DateTime? stableSince = null;
        while (true)
        {
            var (busy, disabled) = await GetPageDataStateAsync(exportToken);
            var now = DateTime.UtcNow;
            if (busy.Length == 0 && disabled is null)
            {
                stableSince ??= now;
                if ((now - stableSince.Value).TotalMilliseconds >= DataSettleStableMs)
                {
                    return (true, busy, disabled);
                }
            }
            else
            {
                stableSince = null;
            }

            if (now >= deadline)
            {
                return (false, busy, disabled);
            }

            await Task.Delay(250);
        }
    }

    private async Task<(string[] Busy, string? Disabled)> GetPageDataStateAsync(string? exportToken)
    {
        try
        {
            var state = await _page.EvaluateAsync<JsonElement>(PageDataStateScript, exportToken ?? string.Empty);
            var busy = state.GetProperty("busy").EnumerateArray().Select(item => item.GetString() ?? string.Empty).ToArray();
            var disabled = state.GetProperty("disabled").ValueKind == JsonValueKind.String
                ? state.GetProperty("disabled").GetString()
                : null;
            return (busy, disabled);
        }
        catch (PlaywrightException exception) when (exception.Message.Contains("context was destroyed", StringComparison.OrdinalIgnoreCase)
            || exception.Message.Contains("navigat", StringComparison.OrdinalIgnoreCase))
        {
            return (new[] { "page is navigating" }, null);
        }
    }

    private async Task WaitForSelectionDataSettledAsync(string fieldLabel)
    {
        var state = await WaitForPageDataSettledAsync(null, DataSettleTimeoutMs);
        if (!state.Settled)
        {
            TestContext.Progress.WriteLine(
                $"Test {TestContext.CurrentContext.Test.Name}: page data was still loading {DataSettleTimeoutMs / 1000}s after selecting " +
                $"'{fieldLabel}' ({string.Join("; ", state.Busy)}); continuing.");
        }
    }

    private async Task<IDownload> WaitForDownloadOrPageMessageAsync(Task<IDownload> downloadTask)
    {
        try
        {
            while (true)
            {
                if (await Task.WhenAny(downloadTask, Task.Delay(500)) == downloadTask)
                {
                    return await downloadTask;
                }

                var message = await GetVisiblePageMessageAsync();
                if (message is not null)
                {
                    _ = downloadTask.ContinueWith(task => task.Exception, TaskContinuationOptions.OnlyOnFaulted);
                    throw new InvalidOperationException(
                        $"Export to Excel did not download a file; the page displayed the message '{message}' on '{_page.Url}'.");
                }
            }
        }
        catch (TimeoutException exception)
        {
            var (busy, _) = await GetPageDataStateAsync(null);
            throw new TimeoutException(
                $"No Excel download started within {ExportDownloadTimeoutMs / 1000}s after clicking Export to Excel on page '{_page.Url}'" +
                (busy.Length > 0 ? $" (page data still loading: {string.Join("; ", busy)})." : "."),
                exception);
        }
    }

    private async Task<string?> GetVisiblePageMessageAsync()
    {
        try
        {
            return await _page.EvaluateAsync<string?>(
                """
                () => {
                    for (const element of document.querySelectorAll('.swal2-popup, .sweet-alert, .toast-message, .toast-error, .k-notification')) {
                        const style = window.getComputedStyle(element);
                        const bounds = element.getBoundingClientRect();
                        const text = (element.innerText || '').replace(/\s+/g, ' ').trim();
                        if (style.display !== 'none' && style.visibility !== 'hidden' && bounds.width > 0 && bounds.height > 0 && text) {
                            return text;
                        }
                    }
                    return null;
                }
                """);
        }
        catch (PlaywrightException)
        {
            return null;
        }
    }

    private async Task AttachExcelDownloadEvidenceAsync(string filename, long fileSize, string artifactDir)
    {
        await _page.EvaluateAsync(
            """
            ({ filename, fileSize }) => {
                document.getElementById('automation-excel-download-evidence')?.remove();
                const panel = document.createElement('aside');
                panel.id = 'automation-excel-download-evidence';
                panel.setAttribute('aria-label', 'Excel download evidence');
                panel.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647;'
                    + 'background:white;color:#163a24;border:3px solid #22863a;border-radius:8px;'
                    + 'padding:16px;max-width:380px;box-shadow:0 4px 16px #0003;'
                    + 'font:14px Arial,sans-serif;overflow-wrap:anywhere;pointer-events:none;';
                for (const text of [
                    'Excel download evidence (automation)',
                    'Action: Export to Excel clicked',
                    'Status: Download completed and saved',
                    `File: ${filename}`,
                    `Size: ${fileSize} bytes`,
                    'Downloaded file attached to test results'
                ]) {
                    const line = document.createElement('div');
                    line.textContent = text;
                    line.style.marginBottom = '8px';
                    panel.appendChild(line);
                }
                document.body.appendChild(panel);
            }
            """,
            new { filename, fileSize });

        var screenshotPath = Path.Combine(artifactDir, $"ExcelDownloadEvidence-{Guid.NewGuid():N}.png");
        await _page.ScreenshotAsync(new PageScreenshotOptions
        {
            Path = screenshotPath,
            FullPage = true,
        });
        TestContext.AddTestAttachment(screenshotPath, "Excel download evidence");
        TestContext.Progress.WriteLine(
            $"Test {TestContext.CurrentContext.Test.Name}: Excel download verified: '{filename}' ({fileSize} bytes). " +
            "Excel file and Excel download evidence screenshot attached.");
    }

    public async Task SelectOptionAsync(string fieldLabel, string optionText)
    {
        if (string.IsNullOrWhiteSpace(fieldLabel))
        {
            throw new ArgumentException("Selector label must be provided.", nameof(fieldLabel));
        }

        if (string.IsNullOrWhiteSpace(optionText))
        {
            throw new ArgumentException(
                $"No value was provided for the '{fieldLabel}' selector. Check the Test Case parameter data.",
                nameof(optionText));
        }

        await WaitForPendingDataRequestsAsync($"before selecting '{optionText}' in '{fieldLabel}'");
        var control = await FindLabelledControlAsync(fieldLabel);
        await control.ScrollIntoViewIfNeededAsync();
        var kind = await control.EvaluateAsync<string>(
            """
            el => el.tagName === 'SELECT' ? 'select'
                : !el.matches('input, textarea') ? 'dropdown'
                : (el.readOnly || (window.jQuery && window.jQuery(el).data('datepicker'))) ? 'datepicker'
                : 'input'
            """);

        switch (kind)
        {
            case "select":
                await SelectNativeOptionAsync(control, fieldLabel, optionText);
                break;
            case "datepicker":
                await SelectBootstrapMonthAsync(control, fieldLabel, optionText);
                break;
            case "input":
                await FillSelectorInputAsync(control, optionText);
                break;
            default:
                await SelectDropdownOptionAsync(control, fieldLabel, optionText);
                break;
        }

        if (kind != "datepicker" && !await IsSelectionAppliedAsync(control, optionText))
        {
            throw new InvalidOperationException(
                $"Selecting '{optionText}' in the '{fieldLabel}' selector did not update the control on page '{_page.Url}'.");
        }

        _appliedSelections.Add($"{fieldLabel} = {optionText}");
        Interlocked.Increment(ref _selectionCount);
        _lastNativeSelection = kind == "select" ? (control, fieldLabel) : null;
        TestContext.Progress.WriteLine(
            $"Test {TestContext.CurrentContext.Test.Name}: selected '{optionText}' in '{fieldLabel}' selector.");
        await WaitForSelectionDataSettledAsync(fieldLabel);
    }

    private async Task SelectBootstrapMonthAsync(ILocator control, string fieldLabel, string optionText)
    {
        var target = ParseMonthYear(optionText) ?? throw new InvalidOperationException(
            $"The '{fieldLabel}' selector is a month picker, but '{optionText}' is not a month and year such as 'Jan-2026'.");

        await control.ClickAsync();
        var picker = _page.Locator(".datepicker.dropdown-menu, .datepicker-dropdown")
            .Filter(new LocatorFilterOptions { Visible = true })
            .First;
        var pickedThroughCalendar = false;
        try
        {
            await picker.WaitForAsync(new LocatorWaitForOptions { State = WaitForSelectorState.Visible, Timeout = 5000 });
            pickedThroughCalendar = await TryPickCalendarMonthAsync(picker, fieldLabel, target);
        }
        catch (TimeoutException)
        {
        }

        var applied = await control.EvaluateAsync<bool>(
            """
            (input, { year, month, picked }) => {
                const $ = window.jQuery;
                const picker = $ ? $(input).data('datepicker') : null;
                if (!picked) {
                    if (!picker) return false;
                    $(input).datepicker('setDate', new Date(year, month - 1, 1));
                }
                if (picker && $('.datepicker-dropdown:visible').length) $(input).datepicker('hide');
                return true;
            }
            """,
            new { year = target.Year, month = target.Month, picked = pickedThroughCalendar });
        if (!applied)
        {
            throw new InvalidOperationException(
                $"The '{fieldLabel}' selector is read-only and did not open a month calendar on page '{_page.Url}'.");
        }

        var selectedValue = await control.InputValueAsync();
        var selected = ParseMonthYear(selectedValue);
        if (selected is null || selected.Value.Year != target.Year || selected.Value.Month != target.Month)
        {
            throw new InvalidOperationException(
                $"Selecting '{optionText}' in the '{fieldLabel}' selector left the value '{selectedValue}' on page '{_page.Url}'.");
        }
    }

    private static async Task<bool> TryPickCalendarMonthAsync(ILocator picker, string fieldLabel, DateTime target)
    {
        var monthsView = picker.Locator(".datepicker-months");
        if (!await monthsView.IsVisibleAsync())
        {
            return false;
        }

        for (var attempt = 0; attempt < 60; attempt++)
        {
            var yearText = (await monthsView.Locator(".datepicker-switch").InnerTextAsync()).Trim();
            if (!int.TryParse(yearText, out var shownYear))
            {
                return false;
            }

            if (shownYear == target.Year)
            {
                var month = monthsView.Locator("span.month").Nth(target.Month - 1);
                if ((await month.GetAttributeAsync("class") ?? string.Empty).Split(' ').Contains("disabled"))
                {
                    throw new InvalidOperationException(
                        $"{target:MMM-yyyy} is disabled in the '{fieldLabel}' month picker; choose a month inside the allowed range.");
                }

                await month.ClickAsync();
                return true;
            }

            var arrow = monthsView.Locator(shownYear < target.Year ? "th.next" : "th.prev");
            if ((await arrow.GetAttributeAsync("class") ?? string.Empty).Contains("disabled"))
            {
                throw new InvalidOperationException(
                    $"{target.Year} is outside the allowed range of the '{fieldLabel}' month picker.");
            }

            await arrow.ClickAsync();
        }

        return false;
    }

    internal static DateTime? ParseMonthYear(string value)
    {
        var formats = new[]
        {
            "MMM-yyyy", "MMMM-yyyy", "MMM yyyy", "MMMM yyyy", "MMM/yyyy", "MMMM/yyyy",
            "MM-yyyy", "M-yyyy", "MM/yyyy", "M/yyyy", "yyyy-MM", "yyyy/MM",
        };
        return DateTime.TryParseExact(
            System.Text.RegularExpressions.Regex.Replace(value ?? string.Empty, @"\s+", " ").Trim(),
            formats,
            System.Globalization.CultureInfo.InvariantCulture,
            System.Globalization.DateTimeStyles.None,
            out var parsed)
            ? parsed
            : null;
    }

    private async Task<ILocator> FindLabelledControlAsync(string fieldLabel)
    {
        var token = Guid.NewGuid().ToString("N");
        try
        {
            await _page.WaitForFunctionAsync(
                """
                ({ label, token }) => {
                    const norm = value => (value || '').replace(/[:*]/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
                    const wanted = norm(label);
                    const bare = wanted.replace(/^select\s+/, '');
                    const names = new Set([wanted, bare, `select ${bare}`]);
                    const isVisible = element => {
                        if (!element) return false;
                        const style = window.getComputedStyle(element);
                        const bounds = element.getBoundingClientRect();
                        return style.display !== 'none' && style.visibility !== 'hidden'
                            && bounds.width > 0 && bounds.height > 0;
                    };
                    const wrapperSelector = '.k-dropdownlist, .k-dropdown, .k-combobox, .k-datepicker, '
                        + '.k-datetimepicker, .k-dateinput, .k-multiselect, .k-picker';
                    const controlSelector = `${wrapperSelector}, [role="combobox"], [role="listbox"], select, textarea, `
                        + 'input:not([type="hidden"]):not([type="button"]):not([type="submit"])'
                        + ':not([type="checkbox"]):not([type="radio"])';
                    const promote = element => {
                        if (!element || element.closest('#automation-excel-download-evidence')) return null;
                        const wrapper = element.closest(wrapperSelector);
                        const candidate = wrapper && isVisible(wrapper) ? wrapper : element;
                        if (!isVisible(candidate)) return null;
                        if (candidate.matches('.k-datepicker, .k-datetimepicker, .k-dateinput, .k-combobox')) {
                            const input = candidate.querySelector('input:not([type="hidden"])');
                            if (isVisible(input)) return input;
                        }
                        return candidate;
                    };
                    const firstControlIn = root => {
                        if (root.matches(controlSelector)) {
                            const promoted = promote(root);
                            if (promoted) return promoted;
                        }
                        for (const element of root.querySelectorAll(controlSelector)) {
                            const promoted = promote(element);
                            if (promoted) return promoted;
                        }
                        return null;
                    };
                    const mark = element => {
                        element.setAttribute('data-automation-selector', token);
                        return true;
                    };

                    for (const element of document.querySelectorAll(controlSelector)) {
                        const accessibleName = [element.getAttribute('aria-label'), element.getAttribute('title'),
                            element.getAttribute('placeholder')].map(norm);
                        if (accessibleName.some(name => names.has(name))) {
                            const promoted = promote(element);
                            if (promoted) return mark(promoted);
                        }
                    }

                    const textElements = Array.from(document.querySelectorAll(
                        'label, span, div, td, th, p, strong, b, legend, dt, h1, h2, h3, h4, h5, h6'))
                        .filter(element => names.has(norm(element.textContent))
                            && !Array.from(element.children).some(child => names.has(norm(child.textContent))))
                        .sort((left, right) => (right.tagName === 'LABEL') - (left.tagName === 'LABEL'));
                    for (const element of textElements) {
                        const forId = element.tagName === 'LABEL' ? element.getAttribute('for') : null;
                        const linked = forId ? promote(document.getElementById(forId)) : null;
                        if (linked) return mark(linked);

                        const owningWrapper = element.closest(wrapperSelector);
                        if (owningWrapper && isVisible(owningWrapper)) return mark(promote(owningWrapper));

                        let node = element;
                        for (let depth = 0; node && depth < 4; depth++, node = node.parentElement) {
                            for (let sibling = node.nextElementSibling; sibling; sibling = sibling.nextElementSibling) {
                                const control = firstControlIn(sibling);
                                if (control) return mark(control);
                            }
                        }
                    }
                    return false;
                }
                """,
                new { label = fieldLabel, token },
                new PageWaitForFunctionOptions { Timeout = 30000, PollingInterval = 250 });
        }
        catch (TimeoutException)
        {
            throw new TimeoutException(
                $"Timeout 30000ms exceeded while waiting for a visible '{fieldLabel}' selector on page '{_page.Url}'.");
        }

        return _page.Locator($"[data-automation-selector='{token}']");
    }

    private async Task SelectNativeOptionAsync(ILocator control, string fieldLabel, string optionText)
    {
        // Options are often filled by an AJAX call after the page loads, so keep checking until the option appears.
        // A selector that stays empty may depend on the previous selection, which the page only applies on change;
        // if that change happened before the page's data arrived, re-apply it as a user would.
        var started = DateTime.UtcNow;
        var lastReapply = started;
        var reapplied = 0;
        string[][] options;
        int index;
        while (true)
        {
            options = await control.EvaluateAsync<string[][]>(
                "select => Array.from(select.options).map(option => [option.value, option.textContent.trim()])");
            index = ChooseOptionIndex(options.Select(option => option[1]).ToList(), optionText);
            if (index < 0)
            {
                index = ChooseOptionIndex(options.Select(option => option[0]).ToList(), optionText);
            }

            var elapsed = (DateTime.UtcNow - started).TotalMilliseconds;
            var limit = options.Length == 0 && _lastNativeSelection is not null
                ? Math.Max(SelectorOptionsTimeoutMs, DependentOptionsTimeoutMs)
                : SelectorOptionsTimeoutMs;
            if (index >= 0 || elapsed >= limit)
            {
                break;
            }

            if (options.Length == 0
                && _lastNativeSelection is { } previous
                && (DateTime.UtcNow - lastReapply).TotalMilliseconds >= ReapplySelectionIntervalMs)
            {
                await WaitForPendingDataRequestsAsync($"before re-applying '{previous.Label}'");
                await previous.Control.EvaluateAsync(
                    "select => { select.dispatchEvent(new Event('input', { bubbles: true })); select.dispatchEvent(new Event('change', { bubbles: true })); }");
                reapplied++;
                lastReapply = DateTime.UtcNow;
                TestContext.Progress.WriteLine(
                    $"Test {TestContext.CurrentContext.Test.Name}: '{fieldLabel}' selector had no options; " +
                    $"re-applied the '{previous.Label}' selection so the page reloads it (attempt {reapplied}).");
                continue;
            }

            await Task.Delay(250);
        }

        if (index < 0)
        {
            var waited = (int)(DateTime.UtcNow - started).TotalMilliseconds;
            var hint = options.Length == 0 && _lastNativeSelection is { } last
                ? $" The page did not fill it after the '{last.Label}' selection was re-applied {reapplied} time(s)."
                : string.Empty;
            throw new InvalidOperationException(
                $"Option '{optionText}' was not found in the '{fieldLabel}' selector within {waited} ms. " +
                $"Available options: {(options.Length == 0 ? "none" : string.Join(", ", options.Select(option => $"'{option[1]}'")))}.{hint}");
        }

        await control.SelectOptionAsync(new SelectOptionValue { Index = index });
    }

    private async Task FillSelectorInputAsync(ILocator control, string optionText)
    {
        await control.ClickAsync();
        await control.FillAsync(optionText);
        await control.PressAsync("Tab");
        await control.EvaluateAsync(
            """
            (input, value) => {
                const widget = window.kendo && window.jQuery ? window.kendo.widgetInstance(window.jQuery(input)) : null;
                if (widget && typeof widget.value === 'function' && !widget.value()) {
                    widget.value(value);
                    widget.trigger('change');
                }
            }
            """,
            optionText);
    }

    private async Task SelectDropdownOptionAsync(ILocator control, string fieldLabel, string optionText)
    {
        await control.ClickAsync();
        var options = _page.Locator(
                "[role='option'], .k-list .k-item, .k-list-item, .k-list-ul > li, .dropdown-menu .dropdown-item")
            .Filter(new LocatorFilterOptions { Visible = true });
        try
        {
            await options.First.WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Visible,
                Timeout = 10000,
            });
        }
        catch (TimeoutException)
        {
            if (await TrySelectKendoValueAsync(control, optionText))
            {
                return;
            }

            throw new TimeoutException(
                $"Timeout 10000ms exceeded while waiting for the '{fieldLabel}' selector options on page '{_page.Url}'.");
        }

        var texts = await options.AllInnerTextsAsync();
        var index = ChooseOptionIndex(texts, optionText);
        if (index >= 0)
        {
            await options.Nth(index).ClickAsync();
            return;
        }

        await _page.Keyboard.PressAsync("Escape");
        if (await TrySelectKendoValueAsync(control, optionText))
        {
            return;
        }

        throw new InvalidOperationException(
            $"Option '{optionText}' was not found in the '{fieldLabel}' selector. " +
            $"Available options: {string.Join(", ", texts.Select(text => $"'{text.Trim()}'"))}.");
    }

    private async Task<bool> TrySelectKendoValueAsync(ILocator control, string optionText)
    {
        return await control.EvaluateAsync<bool>(
            """
            (wrapper, value) => {
                if (!window.kendo || !window.jQuery) return false;
                const norm = text => String(text ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
                const wanted = norm(value);
                for (const element of [wrapper, ...wrapper.querySelectorAll('select, input')]) {
                    const widget = window.kendo.widgetInstance(window.jQuery(element));
                    if (!widget || !widget.dataSource) continue;
                    const textField = widget.options.dataTextField;
                    const valueField = widget.options.dataValueField;
                    const item = widget.dataSource.view().find(dataItem => {
                        const text = typeof dataItem === 'object' && textField ? dataItem[textField] : dataItem;
                        const itemValue = typeof dataItem === 'object' && valueField ? dataItem[valueField] : dataItem;
                        return norm(text) === wanted || norm(itemValue) === wanted;
                    });
                    if (!item) continue;
                    widget.value(typeof item === 'object' && valueField ? item[valueField] : item);
                    widget.trigger('change');
                    return true;
                }
                return false;
            }
            """,
            optionText);
    }

    private static async Task<bool> IsSelectionAppliedAsync(ILocator control, string optionText)
    {
        return await control.EvaluateAsync<bool>(
            """
            (element, value) => {
                const norm = text => String(text ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
                const wanted = norm(value);
                if (element.tagName === 'SELECT') {
                    const option = element.selectedOptions[0];
                    return !!option && (norm(option.textContent).includes(wanted) || norm(option.value) === wanted);
                }
                if (element.matches('input, textarea')) {
                    const widget = window.kendo && window.jQuery ? window.kendo.widgetInstance(window.jQuery(element)) : null;
                    return norm(element.value) === wanted || !!(widget && widget.value && widget.value());
                }
                return norm(element.innerText || element.textContent).includes(wanted)
                    || Array.from(element.querySelectorAll('input, select')).some(input => norm(input.value) === wanted);
            }
            """,
            optionText);
    }

    internal static int ChooseOptionIndex(IReadOnlyList<string> optionTexts, string wanted)
    {
        static string Normalize(string value) =>
            System.Text.RegularExpressions.Regex.Replace(value ?? string.Empty, @"\s+", " ").Trim();

        var normalizedWanted = Normalize(wanted);
        for (var index = 0; index < optionTexts.Count; index++)
        {
            if (Normalize(optionTexts[index]).Equals(normalizedWanted, StringComparison.OrdinalIgnoreCase))
            {
                return index;
            }
        }

        var wordMatch = new System.Text.RegularExpressions.Regex(
            $@"(^|[^A-Za-z0-9]){System.Text.RegularExpressions.Regex.Escape(normalizedWanted)}($|[^A-Za-z0-9])",
            System.Text.RegularExpressions.RegexOptions.IgnoreCase);
        var partialMatches = optionTexts
            .Select((text, index) => (text, index))
            .Where(option => wordMatch.IsMatch(Normalize(option.text)))
            .ToList();
        return partialMatches.Count == 1 ? partialMatches[0].index : -1;
    }

    private async Task ClickControlAsync(string buttonText)
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

    internal static bool IsCustomerDetailsPath(string path)
    {
        return path.TrimEnd('/').Equals(
            "/CustomerDetails/CustomerDetail",
            StringComparison.OrdinalIgnoreCase);
    }

    private async Task NavigateThroughMenuLinkAsync(Uri brokenUri, string menuItem, int status)
    {
        TestContext.Progress.WriteLine(
            $"WARNING: Test Case URL '{brokenUri}' returned HTTP {status}. Opening '{menuItem}' from the portal menu instead.");
        await _page.GotoAsync(brokenUri.GetLeftPart(UriPartial.Authority) + "/", new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
            Timeout = 60000,
        });

        string? href;
        try
        {
            var handle = await _page.WaitForFunctionAsync(
                """
                label => {
                    const norm = text => String(text ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
                    const link = Array.from(document.querySelectorAll('a[href]'))
                        .find(anchor => norm(anchor.textContent) === norm(label) && !/^(#|javascript:)/i.test(anchor.getAttribute('href')));
                    return link ? link.href : false;
                }
                """,
                menuItem,
                new PageWaitForFunctionOptions { Timeout = 30000, PollingInterval = 250 });
            href = await handle.JsonValueAsync<string>();
        }
        catch (TimeoutException)
        {
            throw new InvalidOperationException(
                $"Test Case URL '{brokenUri}' returned HTTP {status} and no '{menuItem}' menu link was found to recover. " +
                "Fix the URL in the Test Case steps.");
        }

        var response = await _page.GotoAsync(href, new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
            Timeout = 60000,
        });
        if (response is not null && response.Status >= 400)
        {
            throw new InvalidOperationException(
                $"The '{menuItem}' menu link '{href}' returned HTTP {response.Status}.");
        }

        TestContext.Progress.WriteLine(
            $"WARNING: '{menuItem}' is at '{new Uri(href).PathAndQuery}'. Update the Test Case URL to baseURL{new Uri(href).PathAndQuery}.");
    }

    private async Task NavigateThroughUtilitiesAsync(Uri targetUri, string navigationItem)
    {
        if (PathsMatch(new Uri(_page.Url).AbsolutePath, targetUri.AbsolutePath))
        {
            return;
        }

        var targetLink = _page.GetByRole(
                AriaRole.Link,
                new PageGetByRoleOptions { Name = navigationItem, Exact = true })
            .Filter(new LocatorFilterOptions { Visible = true });

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

        try
        {
            await targetLink.WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Visible,
                Timeout = 10000,
            });
        }
        catch (TimeoutException)
        {
            TestContext.Progress.WriteLine(
                $"Utilities navigation did not expose '{navigationItem}'. Falling back to direct navigation to '{targetUri.PathAndQuery}'.");
            await _page.GotoAsync(targetUri.ToString(), new PageGotoOptions
            {
                WaitUntil = WaitUntilState.NetworkIdle,
                Timeout = 60000,
            });

            if (!PathsMatch(new Uri(_page.Url).AbsolutePath, targetUri.AbsolutePath))
            {
                throw new InvalidOperationException(
                    $"Direct navigation to '{targetUri.AbsolutePath}' ended at '{_page.Url}'.");
            }

            return;
        }

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

    private async Task WaitForPageReadyAsync(string? navigationItem, bool isCustomerDetailsPage)
    {
        if (navigationItem is null && !isCustomerDetailsPage)
        {
            return;
        }

        if (navigationItem is not null)
        {
            var heading = _page.GetByRole(
                    AriaRole.Heading,
                    new PageGetByRoleOptions { Name = navigationItem, Exact = true })
                .Filter(new LocatorFilterOptions { Visible = true })
                .First;
            await heading.WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Visible,
                Timeout = 60000,
            });

            if (navigationItem.Equals("Unit Details", StringComparison.Ordinal))
            {
                await WaitForUnitDetailsPageReadyWithRetryAsync();
            }
        }

        if (isCustomerDetailsPage)
        {
            await WaitForCustomerDetailsTablesAsync();
        }
    }

    private async Task WaitForUnitDetailsPageReadyWithRetryAsync()
    {
        try
        {
            await WaitForUnitDetailsPageReadyAsync();
            return;
        }
        catch (TimeoutException)
        {
            TestContext.Progress.WriteLine(
                "Unit Details did not render its grid and Refresh control; reloading the page once to recover from delayed page data.");
        }

        await _page.ReloadAsync(new PageReloadOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
            Timeout = 60000,
        });

        try
        {
            await WaitForUnitDetailsPageReadyAsync();
        }
        catch (TimeoutException exception)
        {
            var diagnostics = await GetUnitDetailsReadinessDiagnosticsAsync();
            throw new TimeoutException(
                $"Unit Details still has no ready grid and visible Refresh control after one page reload. {diagnostics}",
                exception);
        }
    }

    private async Task WaitForUnitDetailsPageReadyAsync()
    {
        var grid = _page.Locator("table, [role='grid'], .k-grid")
            .Filter(new LocatorFilterOptions { Visible = true })
            .First;
        await grid.WaitForAsync(new LocatorWaitForOptions
        {
            State = WaitForSelectorState.Visible,
            Timeout = UnitDetailsReadinessTimeoutMs,
        });

        var gridRow = _page.Locator(
                "table tbody tr, [role='grid'] [role='row'], .k-grid tbody tr")
            .Filter(new LocatorFilterOptions { Visible = true })
            .First;
        await gridRow.WaitForAsync(new LocatorWaitForOptions
        {
            State = WaitForSelectorState.Visible,
            Timeout = UnitDetailsReadinessTimeoutMs,
        });

        await GetRefreshControlLocator().WaitForAsync(new LocatorWaitForOptions
        {
            State = WaitForSelectorState.Visible,
            Timeout = UnitDetailsReadinessTimeoutMs,
        });
    }

    private async Task<string> GetUnitDetailsReadinessDiagnosticsAsync()
    {
        return await _page.EvaluateAsync<string>(
            """
            () => {
                const isVisible = element => {
                    const style = window.getComputedStyle(element);
                    const bounds = element.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && bounds.width > 0
                        && bounds.height > 0;
                };
                const grids = Array.from(document.querySelectorAll('table, [role="grid"], .k-grid'))
                    .filter(isVisible);
                const rows = Array.from(document.querySelectorAll(
                    'table tbody tr, [role="grid"] [role="row"], .k-grid tbody tr'))
                    .filter(isVisible);
                const refreshControls = Array.from(document.querySelectorAll(
                    'button, a, [role="button"], input'))
                    .filter(isVisible)
                    .map(element => [
                        element.innerText,
                        element.getAttribute('aria-label'),
                        element.getAttribute('title'),
                        element.getAttribute('class')
                    ].filter(Boolean).join(' ').trim())
                    .filter(label => /refresh|sync|reload|rotate/i.test(label))
                    .slice(0, 5);
                return JSON.stringify({
                    visibleGridCount: grids.length,
                    visibleGridRowCount: rows.length,
                    visibleRefreshControls: refreshControls
                });
            }
            """);
    }

    private async Task TryWaitForApiEvidencePageReadyAsync(string pageUrl)
    {
        var targetUri = new Uri(pageUrl, UriKind.Absolute);
        try
        {
            if (IsCustomerDetailsPath(targetUri.AbsolutePath))
            {
                await WaitForCustomerDetailsTablesAsync(ApiEvidenceReadinessTimeoutMs);
            }
            else if (GetNavigationItem(targetUri.AbsolutePath) is { } navigationItem)
            {
                var heading = _page.GetByRole(
                        AriaRole.Heading,
                        new PageGetByRoleOptions { Name = navigationItem, Exact = true })
                    .Filter(new LocatorFilterOptions { Visible = true })
                    .First;
                await heading.WaitForAsync(new LocatorWaitForOptions
                {
                    State = WaitForSelectorState.Visible,
                    Timeout = ApiEvidenceReadinessTimeoutMs,
                });

                var gridRow = _page.Locator(
                        "table tbody tr, [role='grid'] [role='row'], .k-grid tbody tr")
                    .Filter(new LocatorFilterOptions { Visible = true });
                await gridRow.First.WaitForAsync(new LocatorWaitForOptions
                {
                    State = WaitForSelectorState.Visible,
                    Timeout = ApiEvidenceReadinessTimeoutMs,
                });
            }
        }
        catch (TimeoutException exception)
        {
            TestContext.Progress.WriteLine(
                $"The page did not reach the expected evidence-ready state at '{targetUri.AbsolutePath}' within {ApiEvidenceReadinessTimeoutMs} ms. " +
                $"The API response will still be asserted; the screenshot may show incomplete page data. {exception.Message}");
        }
    }

    private async Task WaitForCustomerDetailsTablesAsync(int timeoutMs = 90000)
    {
        await _page.GetByText("Energy Services", new PageGetByTextOptions { Exact = true })
            .Filter(new LocatorFilterOptions { Visible = true })
            .First.WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Visible,
                Timeout = timeoutMs,
            });
        await _page.GetByText("Customer Details", new PageGetByTextOptions { Exact = true })
            .Filter(new LocatorFilterOptions { Visible = true })
            .First.WaitForAsync(new LocatorWaitForOptions
            {
                State = WaitForSelectorState.Visible,
                Timeout = timeoutMs,
            });

        await _page.WaitForFunctionAsync(
            """
            () => {
                const isVisible = element => {
                    const style = window.getComputedStyle(element);
                    const bounds = element.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && bounds.width > 0
                        && bounds.height > 0;
                };
                const gridSelector = 'table, [role="grid"], .k-grid';
                const populatedGrids = Array.from(document.querySelectorAll(gridSelector))
                    .filter(grid => !grid.parentElement?.closest(gridSelector)
                        && isVisible(grid)
                        && Array.from(grid.querySelectorAll('tbody tr, [role="row"]')).some(row => {
                            if (!isVisible(row)) {
                                return false;
                            }
                            const text = row.innerText.trim();
                            return text.length > 0 && !/no records|no data|loading/i.test(text);
                        }));
                return populatedGrids.length >= 2;
            }
            """,
            null,
            new PageWaitForFunctionOptions { Timeout = timeoutMs });
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
            "[data-bs-original-title*='refresh' i]",
            "[data-testid*='refresh' i]",
        });
        return _page.Locator(refreshSelector)
            .Filter(new LocatorFilterOptions { Visible = true })
            .First;
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

    private const string GridScriptHelpers =
        """
            const norm = value => String(value ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
            const isVisible = element => {
                if (!element) return false;
                const style = window.getComputedStyle(element);
                const bounds = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && bounds.width > 0 && bounds.height > 0;
            };
            const widgetOf = element => window.kendo && window.jQuery ? window.kendo.widgetInstance(window.jQuery(element)) : null;
            const titleOf = th => norm(th.getAttribute('data-title') || th.textContent);
            const headerCells = grid => Array.from(grid.querySelectorAll('th')).filter(th => !th.closest('.k-filter-row'));
            const gridOf = token => document.querySelector(`[data-automation-grid="${token}"]`);
        """;

    private const string LocateGridScript =
        "({ featureName, token, columns }) => {" + GridScriptHelpers +
        """
            const name = norm(featureName);
            const grids = Array.from(document.querySelectorAll('.k-grid')).filter(isVisible);
            if (!grids.length) return { error: 'No grid is displayed on the page.' };
            const headings = Array.from(document.querySelectorAll(
                'h1, h2, h3, h4, h5, h6, legend, .ibox-title, .panel-heading, .card-header, .page-title'))
                .filter(heading => isVisible(heading) && !heading.closest('.k-grid'));
            const matches = headings.filter(heading => norm(heading.textContent) === name)
                .concat(headings.filter(heading => norm(heading.textContent) !== name && norm(heading.textContent).includes(name)));
            let grid = null;
            let how = '';
            for (const heading of matches) {
                grid = grids.find(candidate => heading.compareDocumentPosition(candidate) & Node.DOCUMENT_POSITION_FOLLOWING) || null;
                if (grid) { how = `first grid after the '${heading.textContent.trim()}' heading`; break; }
            }
            if (!grid) {
                grid = grids.find(candidate => columns.every(column => headerCells(candidate).some(th => titleOf(th) === norm(column)))) || null;
                how = `no '${featureName}' heading found; first grid with the requested columns`;
            }
            if (!grid) return { error: `No '${featureName}' heading and no grid with the columns ${columns.join(', ')} were found.` };
            grid.setAttribute('data-automation-grid', token);
            const missing = columns.filter(column => !headerCells(grid).some(th => titleOf(th) === norm(column)));
            return { how, gridId: grid.id || '', missing };
        }
        """;

    private const string GridStateScript =
        "({ token, field }) => {" + GridScriptHelpers +
        """
            const grid = gridOf(token);
            const widget = grid ? widgetOf(grid) : null;
            const dataSource = widget && widget.dataSource;
            if (!dataSource) return { error: 'The grid has no Kendo data source.' };
            const flatten = filter => !filter ? [] : filter.filters ? filter.filters.flatMap(flatten) : [filter];
            const view = Array.prototype.slice.call(dataSource.view() || []);
            return {
                loading: !!dataSource._requestInProgress || Array.from(grid.querySelectorAll('.k-loading-mask')).some(isVisible),
                rows: view.length,
                total: Number(dataSource.total()) || 0,
                pageSize: Number(dataSource.pageSize()) || 0,
                page: Number(dataSource.page()) || 1,
                filterFields: flatten(dataSource.filter()).map(filter => String(filter.field || '')),
                values: field ? view.map(item => item[field] == null ? '' : String(item[field])) : [],
            };
        }
        """;

    private const string MarkGridFilterInputScript =
        "({ token, title, marker }) => {" + GridScriptHelpers +
        """
            const grid = gridOf(token);
            const header = headerCells(grid).find(th => titleOf(th) === norm(title));
            if (!header) return { error: `The grid has no '${title}' column.` };
            const field = header.getAttribute('data-field') || '';
            let input = null;
            if (field) {
                const cell = Array.from(grid.querySelectorAll('.k-filter-row [data-field]')).find(element => element.getAttribute('data-field') === field);
                input = cell ? Array.from(cell.querySelectorAll('input')).find(isVisible) || null : null;
            }
            if (!input) {
                const index = Array.from(header.parentElement.children).indexOf(header);
                const filterRow = header.closest('thead, table')?.querySelector('tr.k-filter-row') || grid.querySelector('tr.k-filter-row');
                const cell = filterRow ? filterRow.children[index] : null;
                input = cell ? Array.from(cell.querySelectorAll('input')).find(isVisible) || null : null;
            }
            if (!field) return { error: `The '${title}' column has no data field.` };
            if (!input) return { error: `The '${title}' column has no filter box in the grid's filter row.` };
            input.setAttribute('data-automation-filter', marker);
            return { field };
        }
        """;

    private const string MarkGridNextPageScript =
        "({ token, marker }) => {" + GridScriptHelpers +
        """
            const grid = gridOf(token);
            const pager = Array.from(grid.querySelectorAll('.k-pager-wrap, .k-pager, .k-grid-pager')).find(isVisible);
            if (!pager) return { error: 'The grid has no visible pager.' };
            const next = Array.from(pager.querySelectorAll('a, button')).find(element =>
                /next\s+page/i.test(`${element.getAttribute('title') || ''} ${element.getAttribute('aria-label') || ''}`));
            if (!next) return { error: "The grid's pager has no 'next page' button." };
            const disabled = next.matches('.k-state-disabled, .k-disabled, [disabled]') || next.getAttribute('aria-disabled') === 'true';
            next.setAttribute('data-automation-next-page', marker);
            return { disabled, pagerText: (pager.textContent || '').replace(/\s+/g, ' ').trim() };
        }
        """;

    // Checks a "Verify the <feature> feature" step: the grid under the feature's heading shows rows for the current
    // selections, each named column filter narrows the rows to matching values, and the pager moves to the next page.
    public async Task VerifyGridFeatureAsync(string featureName, IReadOnlyList<string> filterColumns, bool verifyPagination)
    {
        if (string.IsNullOrWhiteSpace(featureName))
        {
            throw new ArgumentException("Feature name must be provided.", nameof(featureName));
        }

        ArgumentNullException.ThrowIfNull(filterColumns);
        var token = Guid.NewGuid().ToString("N");
        var selections = _appliedSelections.Count > 0 ? string.Join("; ", _appliedSelections) : "none";
        var located = await _page.EvaluateAsync<JsonElement>(
            LocateGridScript,
            new { featureName, token, columns = filterColumns.ToArray() });
        if (located.TryGetProperty("error", out var locateError))
        {
            throw new InvalidOperationException($"'{featureName}' grid: {locateError.GetString()} Page: {_page.Url}.");
        }

        var missingColumns = located.GetProperty("missing").EnumerateArray().Select(item => item.GetString()).ToArray();
        if (missingColumns.Length > 0)
        {
            throw new InvalidOperationException(
                $"'{featureName}' grid ({located.GetProperty("how").GetString()}) has no column named {string.Join(", ", missingColumns)}.");
        }

        var gridLabel = $"'{featureName}' grid" + (located.GetProperty("gridId").GetString() is { Length: > 0 } id ? $" (#{id})" : string.Empty);
        var isSummaryPaymentGrid = string.Equals(
            located.GetProperty("gridId").GetString(), "SummaryTablePayment", StringComparison.OrdinalIgnoreCase);
        var timeoutMs = isSummaryPaymentGrid ? SummaryPaymentAvailabilityTimeoutMs : DataSettleTimeoutMs;
        await _page.Locator($"[data-automation-grid='{token}']").ScrollIntoViewIfNeededAsync();
        await WaitForPendingDataRequestsAsync($"before checking the {gridLabel}");

        var (initial, loaded) = await WaitForGridStateAsync(token, null, state => state.Rows > 0, timeoutMs);
        if (!loaded)
        {
            throw new InvalidOperationException(
                $"The {gridLabel} " +
                (initial.Loading ? "was still loading its data" : "showed no records") +
                $" after {timeoutMs} ms (selections: {selections}). " +
                "Filtering and pagination cannot be checked without data; check the Test Case's selected options.");
        }

        var results = new List<string>
        {
            $"Grid: {featureName} — {located.GetProperty("how").GetString()}",
            $"Selections: {selections}",
            $"Displayed: {initial.Rows} rows on page {initial.Page} of {initial.Total} records",
        };

        for (var index = 0; index < filterColumns.Count; index++)
        {
            results.Add(await VerifyGridColumnFilterAsync(token, gridLabel, filterColumns[index], $"{token}-{index}", timeoutMs));
        }

        if (verifyPagination)
        {
            results.Add(await VerifyGridPaginationAsync(token, gridLabel, timeoutMs));
        }

        foreach (var line in results)
        {
            TestContext.Progress.WriteLine($"Test {TestContext.CurrentContext.Test.Name}: {line}");
        }

        await AttachGridFeatureEvidenceAsync(token, results);
    }

    private async Task<string> VerifyGridColumnFilterAsync(string token, string gridLabel, string column, string marker, int timeoutMs)
    {
        var mark = await _page.EvaluateAsync<JsonElement>(MarkGridFilterInputScript, new { token, title = column, marker });
        if (mark.TryGetProperty("error", out var markError))
        {
            throw new InvalidOperationException($"{gridLabel}: {markError.GetString()}");
        }

        var field = mark.GetProperty("field").GetString()!;
        var (before, _) = await WaitForGridStateAsync(token, field, state => state.Rows > 0, timeoutMs);
        var sample = before.Values.Select(value => value.Trim()).FirstOrDefault(value => value.Length > 0)
            ?? throw new InvalidOperationException($"{gridLabel}: the '{column}' column has no value to filter by on the current page.");

        var input = _page.Locator($"[data-automation-filter='{marker}']");
        await ApplyGridFilterTextAsync(input, sample);
        var (filtered, applied) = await WaitForGridStateAsync(
            token,
            field,
            state => state.FilterFields.Contains(field, StringComparer.OrdinalIgnoreCase),
            timeoutMs);
        if (!applied)
        {
            throw new InvalidOperationException(
                $"{gridLabel}: typing '{sample}' in the '{column}' filter did not filter the grid within {timeoutMs} ms.");
        }

        var mismatches = filtered.Values
            .Where(value => value.IndexOf(sample, StringComparison.OrdinalIgnoreCase) < 0)
            .ToArray();
        if (filtered.Rows == 0 || mismatches.Length > 0)
        {
            throw new InvalidOperationException(
                $"{gridLabel}: filtering '{column}' by '{sample}' returned {filtered.Rows} rows" +
                (mismatches.Length > 0 ? $", including values that do not contain it: {string.Join(", ", mismatches.Take(5))}." : "."));
        }

        await ApplyGridFilterTextAsync(input, string.Empty);
        bool HasNoFilter(GridState state) => !state.FilterFields.Contains(field, StringComparer.OrdinalIgnoreCase);
        var (_, cleared) = await WaitForGridStateAsync(
            token, field, HasNoFilter,
            timeoutMs == SummaryPaymentAvailabilityTimeoutMs ? timeoutMs : GridFilterClearTimeoutMs);
        if (!cleared)
        {
            var clearButton = _page.Locator(
                $"[data-automation-grid='{token}'] .k-filter-row th:has([data-automation-filter='{marker}']) " +
                ":is(button, a, span)[title='Clear'], " +
                $"[data-automation-grid='{token}'] .k-filter-row th:has([data-automation-filter='{marker}']) .k-clear-value");
            if (await clearButton.CountAsync() > 0 && await clearButton.First.IsVisibleAsync())
            {
                await clearButton.First.ClickAsync();
                (_, cleared) = await WaitForGridStateAsync(token, field, HasNoFilter, timeoutMs);
            }
        }

        if (!cleared)
        {
            throw new InvalidOperationException($"{gridLabel}: clearing the '{column}' filter did not remove it.");
        }

        return $"Filter '{column}' contains '{sample}': {filtered.Total} records (was {before.Total}), all shown rows match; filter cleared";
    }

    private static async Task ApplyGridFilterTextAsync(ILocator input, string text)
    {
        await input.FillAsync(text);
        await input.PressAsync("Enter");
        // Leaving the box raises the filter's change event when Enter only closed the suggestion list.
        await input.PressAsync("Tab");
    }

    private async Task<string> VerifyGridPaginationAsync(string token, string gridLabel, int timeoutMs)
    {
        var (state, _) = await WaitForGridStateAsync(token, null, current => current.Rows > 0, timeoutMs);
        var marker = Guid.NewGuid().ToString("N");
        var pager = await _page.EvaluateAsync<JsonElement>(MarkGridNextPageScript, new { token, marker });
        if (pager.TryGetProperty("error", out var pagerError))
        {
            throw new InvalidOperationException($"{gridLabel}: {pagerError.GetString()}");
        }

        if (state.Total <= state.PageSize || state.PageSize == 0)
        {
            return $"Pagination: pager shown ('{pager.GetProperty("pagerText").GetString()}'); only one page of " +
                $"{state.Total} records with page size {state.PageSize}, so there is no next page to open";
        }

        if (pager.GetProperty("disabled").GetBoolean())
        {
            throw new InvalidOperationException(
                $"{gridLabel}: {state.Total} records with page size {state.PageSize}, but the 'next page' button is disabled.");
        }

        var startPage = state.Page;
        await _page.Locator($"[data-automation-next-page='{marker}']").ClickAsync();
        var (next, moved) = await WaitForGridStateAsync(
            token, null, current => current.Page == startPage + 1 && current.Rows > 0, timeoutMs);
        if (!moved)
        {
            throw new InvalidOperationException(
                $"{gridLabel}: clicking 'next page' did not show page {startPage + 1} within {timeoutMs} ms (still page {next.Page}, {next.Rows} rows).");
        }

        return $"Pagination: moved from page {startPage} to page {next.Page}, showing {next.Rows} of {next.Total} records";
    }

    private async Task<(GridState State, bool Satisfied)> WaitForGridStateAsync(
        string token,
        string? field,
        Func<GridState, bool> condition,
        int? timeoutMs = null)
    {
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs ?? DataSettleTimeoutMs);
        DateTime? satisfiedSince = null;
        while (true)
        {
            var element = await _page.EvaluateAsync<JsonElement>(GridStateScript, new { token, field });
            if (element.TryGetProperty("error", out var error))
            {
                throw new InvalidOperationException($"Grid check failed: {error.GetString()}");
            }

            var state = new GridState(
                element.GetProperty("loading").GetBoolean(),
                element.GetProperty("rows").GetInt32(),
                element.GetProperty("total").GetInt32(),
                element.GetProperty("pageSize").GetInt32(),
                element.GetProperty("page").GetInt32(),
                element.GetProperty("filterFields").EnumerateArray().Select(item => item.GetString() ?? string.Empty).ToArray(),
                element.GetProperty("values").EnumerateArray().Select(item => item.GetString() ?? string.Empty).ToArray());
            var now = DateTime.UtcNow;
            if (!state.Loading && condition(state))
            {
                satisfiedSince ??= now;
                if ((now - satisfiedSince.Value).TotalMilliseconds >= DataSettleStableMs)
                {
                    return (state, true);
                }
            }
            else
            {
                satisfiedSince = null;
            }

            if (now >= deadline)
            {
                return (state, false);
            }

            await Task.Delay(200);
        }
    }

    private async Task AttachGridFeatureEvidenceAsync(string token, IReadOnlyList<string> lines)
    {
        await _page.EvaluateAsync(
            """
            ({ token, lines }) => {
                document.getElementById('automation-grid-feature-evidence')?.remove();
                const panel = document.createElement('aside');
                panel.id = 'automation-grid-feature-evidence';
                panel.setAttribute('aria-label', 'Grid feature evidence');
                panel.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647;'
                    + 'background:white;color:#163a24;border:3px solid #22863a;border-radius:8px;'
                    + 'padding:12px;max-width:460px;box-shadow:0 4px 16px #0003;'
                    + 'font:13px Arial,sans-serif;overflow-wrap:anywhere;pointer-events:none;';
                for (const text of ['Grid feature evidence (automation)', ...lines]) {
                    const line = document.createElement('div');
                    line.textContent = text;
                    line.style.marginBottom = '6px';
                    panel.appendChild(line);
                }
                document.body.appendChild(panel);
                // Keep the grid and its pager in the lower part of the screenshot, below the panel.
                document.querySelector(`[data-automation-grid="${token}"]`)?.scrollIntoView({ block: 'end' });
            }
            """,
            new { token, lines });

        var artifactDir = Path.Combine(TestContext.CurrentContext.WorkDirectory, "TestResults");
        Directory.CreateDirectory(artifactDir);
        var screenshotPath = Path.Combine(artifactDir, $"GridFeatureEvidence-{Guid.NewGuid():N}.png");
        await _page.ScreenshotAsync(new PageScreenshotOptions { Path = screenshotPath });
        TestContext.AddTestAttachment(screenshotPath, "Grid feature evidence");
    }

    private sealed record GridState(
        bool Loading,
        int Rows,
        int Total,
        int PageSize,
        int Page,
        string[] FilterFields,
        string[] Values);

    private static string NormalizeApiPathFragment(string apiPathFragment)
    {
        var normalized = apiPathFragment.Trim();
        if (!normalized.StartsWith("/"))
        {
            normalized = $"/{normalized}";
        }

        return normalized;
    }

    private async Task<ApiResponseCapture> FetchApiResponseWithBrowserCookiesAsync(
        string pageUrl,
        string apiPathFragment,
        IReadOnlyList<KeyValuePair<string, string>>? payload = null)
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
            AllowAutoRedirect = false,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate | DecompressionMethods.Brotli,
        };
        using var client = new HttpClient(handler);
        client.Timeout = TimeSpan.FromMilliseconds(
            ResolveApiTimeoutMs(requestUri.AbsolutePath, (int)client.Timeout.TotalMilliseconds));
        client.DefaultRequestHeaders.Add("Accept", "application/json, text/plain, */*");
        // The page's own jQuery/Kendo calls send this header; some MVC actions only answer AJAX requests.
        client.DefaultRequestHeaders.Add("X-Requested-With", "XMLHttpRequest");
        if (payload is null)
        {
            using var getResponse = await client.GetAsync(requestUri);
            return new ApiResponseCapture(
                (int)getResponse.StatusCode,
                requestUri.ToString(),
                await getResponse.Content.ReadAsStringAsync(),
                Method: "GET");
        }

        using var content = new FormUrlEncodedContent(payload);
        using var response = await client.PostAsync(requestUri, content);
        var responseBody = await response.Content.ReadAsStringAsync();

        return new ApiResponseCapture(
            (int)response.StatusCode,
            requestUri.ToString(),
            responseBody,
            Method: "POST (form data from the Test Case, sent with the signed-in session)",
            Payload: string.Join("&", payload.Select(field => $"{field.Key}={field.Value}")));
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
            @"({ requestUrl, statusCode, responsePreview, method, selections, payload }) => {
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
                if (selections) {
                    // Keep the filters at the top of the page visible in the screenshot.
                    panel.style.top = 'auto';
                    panel.style.bottom = '48px';
                }

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

                const addLine = (label, value) => {
                    const line = document.createElement('div');
                    line.textContent = `${label}: ${value}`;
                    line.style.marginBottom = '8px';
                    line.style.whiteSpace = 'pre-wrap';
                    line.style.wordBreak = 'break-word';
                    panel.appendChild(line);
                };
                if (method) addLine('Method', method);
                if (selections) addLine('Selected before the call', selections);
                if (payload !== null && payload !== undefined) addLine('Payload sent', payload || '<empty>');

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
                method = capture.Method,
                selections = capture.Selections,
                payload = capture.Payload,
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

    private sealed class UnitDetailsNavigationDiagnostics : IDisposable
    {
        private const int MaxEntries = 20;
        private readonly IPage _page;
        private readonly List<string> _entries = new();
        private readonly EventHandler<IRequest> _requestFailedHandler;
        private readonly EventHandler<IResponse> _responseHandler;
        private readonly EventHandler<string> _pageErrorHandler;

        public UnitDetailsNavigationDiagnostics(IPage page)
        {
            _page = page;
            _requestFailedHandler = (_, request) =>
                Add($"Request failed: {request.Method} {GetSafeUrl(request.Url)} ({request.Failure ?? "unknown"}).");
            _responseHandler = (_, response) =>
            {
                if (response.Status >= 400)
                {
                    Add($"HTTP {response.Status}: {response.Request.Method} {GetSafeUrl(response.Url)}.");
                }
            };
            _pageErrorHandler = (_, error) =>
            {
                var errorType = error.Split(':', 2)[0].Trim();
                Add($"Uncaught page error: {Truncate(errorType, 120)}.");
            };

            _page.RequestFailed += _requestFailedHandler;
            _page.Response += _responseHandler;
            _page.PageError += _pageErrorHandler;
        }

        public string GetSummary()
        {
            return _entries.Count == 0
                ? "No failed requests, HTTP errors, or uncaught page errors were observed."
                : string.Join(" ", _entries);
        }

        public void Dispose()
        {
            _page.RequestFailed -= _requestFailedHandler;
            _page.Response -= _responseHandler;
            _page.PageError -= _pageErrorHandler;
        }

        private void Add(string entry)
        {
            if (_entries.Count == MaxEntries)
            {
                _entries.RemoveAt(0);
            }

            _entries.Add(entry);
        }

        private static string GetSafeUrl(string url)
        {
            return Uri.TryCreate(url, UriKind.Absolute, out var uri)
                ? $"{uri.GetLeftPart(UriPartial.Authority)}{uri.AbsolutePath}"
                : "<unavailable URL>";
        }

        private static string Truncate(string value, int maxLength)
        {
            return value.Length <= maxLength
                ? value
                : $"{value[..maxLength]}...";
        }
    }

    private sealed record ApiResponseCapture(
        int StatusCode,
        string RequestUrl,
        string ResponseBody,
        string? Method = null,
        string? Selections = null,
        string? Payload = null);

    private sealed class ApiCallWatch(string path)
    {
        public string Path { get; } = path;
        public List<(IRequest Request, int SelectionCount)> Calls { get; } = new();
        public EventHandler<IRequest>? Handler { get; set; }
    }
}
