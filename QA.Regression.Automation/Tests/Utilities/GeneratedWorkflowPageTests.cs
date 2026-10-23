using System;
using NUnit.Framework;
using QA.Regression.Automation.Pages;

namespace QA.Regression.Automation.Tests.Utilities;

[TestFixture]
public class GeneratedWorkflowPageTests
{
    [TestCase("/UnitDetails/UnitDetail", "Unit Details")]
    [TestCase("/unitdetails/unitdetail/", "Unit Details")]
    [TestCase("/CustomerDetails/CustomerDetail", "Customer Details")]
    [TestCase("/customerDetails/customerdetail/", "Customer Details")]
    public void GetNavigationItem_MapsApplicationRoutesToMenuItems(string path, string expectedMenuItem)
    {
        Assert.That(GeneratedWorkflowPage.GetNavigationItem(path), Is.EqualTo(expectedMenuItem));
    }

    [Test]
    public void GetNavigationItem_ReturnsNullForUnmappedRoutes()
    {
        Assert.That(GeneratedWorkflowPage.GetNavigationItem("/Dashboard/Index"), Is.Null);
    }

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
