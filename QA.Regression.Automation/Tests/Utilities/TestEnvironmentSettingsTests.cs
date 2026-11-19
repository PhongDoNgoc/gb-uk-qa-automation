using System;
using System.Collections.Generic;
using NUnit.Framework;
using QA.Regression.Automation.Utilities;

namespace QA.Regression.Automation.Tests.Utilities;

[TestFixture]
[NonParallelizable]
public class TestEnvironmentSettingsTests
{
    private string? _originalTargetEnvironment;
    private string? _originalDevBaseUrl;

    [SetUp]
    public void SetUp()
    {
        _originalTargetEnvironment = Environment.GetEnvironmentVariable("TEST_TARGET_ENV");
        _originalDevBaseUrl = Environment.GetEnvironmentVariable("VIEWPOINT_BASE_URL_DEV");
        Environment.SetEnvironmentVariable("TEST_TARGET_ENV", "DEV");
        Environment.SetEnvironmentVariable("VIEWPOINT_BASE_URL_DEV", "https://dev.example.test");
    }

    [TearDown]
    public void TearDown()
    {
        Environment.SetEnvironmentVariable("TEST_TARGET_ENV", _originalTargetEnvironment);
        Environment.SetEnvironmentVariable("VIEWPOINT_BASE_URL_DEV", _originalDevBaseUrl);
    }

    [TestCase("/UnitDetails/UnitDetail", "https://dev.example.test/UnitDetails/UnitDetail")]
    [TestCase("UnitDetails/UnitDetail", "https://dev.example.test/UnitDetails/UnitDetail")]
    public void ResolveUrlForEnvironment_AcceptsRelativePaths(string path, string expectedUrl)
    {
        Assert.That(TestEnvironmentSettings.ResolveUrlForEnvironment(path), Is.EqualTo(expectedUrl));
    }

    [TestCase("https://other.example.test/UnitDetails/UnitDetail")]
    [TestCase("//other.example.test/UnitDetails/UnitDetail")]
    public void ResolveUrlForEnvironment_RejectsAbsoluteAndNetworkPathReferences(string path)
    {
        Assert.Throws<InvalidOperationException>(
            () => TestEnvironmentSettings.ResolveUrlForEnvironment(path));
    }

    [TestCase("DEV", "dev-id")]
    [TestCase("STAGE", "stage-id")]
    public void ResolveEnvironmentSpecificValue_UsesSelectedEnvironment(string environment, string expectedValue)
    {
        Environment.SetEnvironmentVariable("TEST_TARGET_ENV", environment);
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["DEV"] = "dev-id",
            ["STAGE"] = "stage-id",
        };

        Assert.That(
            TestEnvironmentSettings.ResolveEnvironmentSpecificValue(values),
            Is.EqualTo(expectedValue));
    }

    [Test]
    public void ResolveEnvironmentSpecificValue_FailsWhenSelectedEnvironmentIsMissing()
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["STAGE"] = "stage-id",
        };

        var exception = Assert.Throws<InvalidOperationException>(
            () => TestEnvironmentSettings.ResolveEnvironmentSpecificValue(values));

        Assert.That(exception!.Message, Does.Contain("'DEV'"));
    }
}
