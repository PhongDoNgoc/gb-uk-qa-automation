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
                await _page.GotoAsync(url, new PageGotoOptions
                {
                    WaitUntil = WaitUntilState.DOMContentLoaded,
                    Timeout = 60000,
                });
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

        var download = await _page.RunAndWaitForDownloadAsync(
            async () =>
            {
                await exportControl.ClickAsync(new LocatorClickOptions { Timeout = 60000 });
                TestContext.Progress.WriteLine(
                    $"Test {TestContext.CurrentContext.Test.Name}: visible Export to Excel control clicked; waiting for download.");
            },
            new PageRunAndWaitForDownloadOptions { Timeout = 60000 });
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

        var control = await FindLabelledControlAsync(fieldLabel);
        await control.ScrollIntoViewIfNeededAsync();
        var kind = await control.EvaluateAsync<string>(
            "el => el.tagName === 'SELECT' ? 'select' : (el.matches('input, textarea') ? 'input' : 'dropdown')");

        switch (kind)
        {
            case "select":
                await SelectNativeOptionAsync(control, fieldLabel, optionText);
                break;
            case "input":
                await FillSelectorInputAsync(control, optionText);
                break;
            default:
                await SelectDropdownOptionAsync(control, fieldLabel, optionText);
                break;
        }

        if (!await IsSelectionAppliedAsync(control, optionText))
        {
            throw new InvalidOperationException(
                $"Selecting '{optionText}' in the '{fieldLabel}' selector did not update the control on page '{_page.Url}'.");
        }

        TestContext.Progress.WriteLine(
            $"Test {TestContext.CurrentContext.Test.Name}: selected '{optionText}' in '{fieldLabel}' selector.");
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
        var options = await control.EvaluateAsync<string[][]>(
            "select => Array.from(select.options).map(option => [option.value, option.textContent.trim()])");
        var index = ChooseOptionIndex(options.Select(option => option[1]).ToList(), optionText);
        if (index < 0)
        {
            index = ChooseOptionIndex(options.Select(option => option[0]).ToList(), optionText);
        }

        if (index < 0)
        {
            throw new InvalidOperationException(
                $"Option '{optionText}' was not found in the '{fieldLabel}' selector. " +
                $"Available options: {string.Join(", ", options.Select(option => $"'{option[1]}'"))}.");
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
            AllowAutoRedirect = false,
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

    private sealed record ApiResponseCapture(int StatusCode, string RequestUrl, string ResponseBody);
}
