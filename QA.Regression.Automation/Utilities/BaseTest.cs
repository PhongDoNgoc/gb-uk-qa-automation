using Microsoft.Playwright;
using NUnit.Framework;
using NUnit.Framework.Interfaces;

namespace QA.Regression.Automation.Utilities;

public class BaseTest
{
    protected IPage Page = null!;
    protected IBrowser Browser = null!;
    protected IBrowserContext Context = null!;
    private IPlaywright? _playwright;

    [SetUp]
    public async Task SetUp()
    {
        _playwright = await Playwright.CreateAsync();
        Browser = await _playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
        {
            Headless = ResolveHeadlessMode(),
        });

        Context = await Browser.NewContextAsync(new BrowserNewContextOptions
        {
            ViewportSize = new ViewportSize { Width = 1440, Height = 900 },
        });
        await Context.Tracing.StartAsync(new TracingStartOptions
        {
            Screenshots = true,
            Snapshots = true,
            Sources = true,
        });

        Page = await Context.NewPageAsync();
    }

    [TearDown]
    public async Task TearDown()
    {
        var artifactDir = Path.Combine(TestContext.CurrentContext.WorkDirectory, "TestResults");
        Directory.CreateDirectory(artifactDir);

        var testName = SanitizeFileName(TestContext.CurrentContext.Test.Name);
        var tracePath = Path.Combine(artifactDir, $"{testName}.zip");
        await Context.Tracing.StopAsync(new TracingStopOptions { Path = tracePath });
        TestContext.AddTestAttachment(tracePath, "Playwright trace");

        if (TestContext.CurrentContext.Result.Outcome.Status == TestStatus.Failed)
        {
            var screenshotPath = Path.Combine(artifactDir, $"{testName}.png");
            await Page.ScreenshotAsync(new PageScreenshotOptions
            {
                Path = screenshotPath,
                FullPage = true,
            });
            TestContext.AddTestAttachment(screenshotPath, "Failure screenshot");
        }

        await Context.CloseAsync();
        await Browser.CloseAsync();
        _playwright?.Dispose();
    }

    private static bool ResolveHeadlessMode()
    {
        var raw = Environment.GetEnvironmentVariable("HEADLESS");
        if (string.IsNullOrWhiteSpace(raw))
        {
            return true;
        }

        return !raw.Equals("false", StringComparison.OrdinalIgnoreCase)
            && !raw.Equals("0", StringComparison.OrdinalIgnoreCase)
            && !raw.Equals("no", StringComparison.OrdinalIgnoreCase);
    }

    private static string SanitizeFileName(string value)
    {
        foreach (var invalid in Path.GetInvalidFileNameChars())
        {
            value = value.Replace(invalid, '_');
        }

        return value;
    }
}
