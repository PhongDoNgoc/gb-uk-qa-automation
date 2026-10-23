using System;
using NUnit.Framework;
using QA.Regression.Automation.Pages;

namespace QA.Regression.Automation.Tests.Utilities;

[TestFixture]
public class GeneratedWorkflowPageTests
{
    [Test]
    public void BuildRequestUri_CombinesRootedApiPathWithPageOrigin()
    {
        var requestUri = GeneratedWorkflowPage.BuildRequestUri(
            "https://dev.example.test/CustomerDetails/CustomerDetail",
            "/CustomerDetails/EnergyServiceDetails");

        Assert.That(
            requestUri.AbsoluteUri,
            Is.EqualTo("https://dev.example.test/CustomerDetails/EnergyServiceDetails"));
    }

    [Test]
    public void BuildRequestUri_PreservesAbsoluteHttpApiUrl()
    {
        var requestUri = GeneratedWorkflowPage.BuildRequestUri(
            "https://dev.example.test/CustomerDetails/CustomerDetail",
            "https://api.example.test/CustomerDetails/EnergyServiceDetails");

        Assert.That(
            requestUri.AbsoluteUri,
            Is.EqualTo("https://api.example.test/CustomerDetails/EnergyServiceDetails"));
    }

    [TestCase("file:///tmp/page.html")]
    [TestCase("/CustomerDetails/CustomerDetail")]
    public void BuildRequestUri_RejectsNonHttpPageUrls(string pageUrl)
    {
        Assert.Throws<InvalidOperationException>(
            () => GeneratedWorkflowPage.BuildRequestUri(pageUrl, "/api/endpoint"));
    }

    [TestCase("file:///tmp/api.json")]
    [TestCase("ftp://api.example.test/endpoint")]
    public void BuildRequestUri_RejectsUnsupportedAbsoluteApiUrls(string apiUrl)
    {
        Assert.Throws<InvalidOperationException>(
            () => GeneratedWorkflowPage.BuildRequestUri(
                "https://dev.example.test/page",
                apiUrl));
    }

    [Test]
    public void BuildRequestUri_RejectsNetworkPathApiReferences()
    {
        Assert.Throws<InvalidOperationException>(
            () => GeneratedWorkflowPage.BuildRequestUri(
                "https://dev.example.test/page",
                "//other.example.test/api/endpoint"));
    }
}
