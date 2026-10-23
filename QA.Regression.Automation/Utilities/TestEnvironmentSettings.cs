using System.Text;

namespace QA.Regression.Automation.Utilities;

public static class TestEnvironmentSettings
{
    private const string LegacyProdBaseUrlVariableName = "VIEWPOINT_BASE_URL";

    public static string RequireEnvironmentVariable(string name)
    {
        var value = ResolveOptionalEnvironmentVariable(name);
        if (!string.IsNullOrWhiteSpace(value))
        {
            return value;
        }

        throw new InvalidOperationException(
            $"Required environment variable '{name}' is not configured."
        );
    }

    public static string? ResolveOptionalEnvironmentVariable(string name)
    {
        var value = Environment.GetEnvironmentVariable(name);
        return string.IsNullOrWhiteSpace(value) ? null : value;
    }

    public static string ResolveBaseUrlForEnvironment()
    {
        var selectedEnvironment = ResolveEnvironmentName();
        return ResolveConfiguredBaseUri(selectedEnvironment).ToString();
    }

    public static string ResolveUrlForEnvironment(string relativeUrl)
    {
        if (string.IsNullOrWhiteSpace(relativeUrl))
        {
            return ResolveBaseUrlForEnvironment();
        }

        var normalizedUrl = relativeUrl.Trim();
        if (normalizedUrl == "/")
        {
            return ResolveBaseUrlForEnvironment();
        }

        if (normalizedUrl.StartsWith("//", StringComparison.Ordinal))
        {
            throw new InvalidOperationException(
                $"Expected a relative URL path, but received a network-path reference: '{relativeUrl}'."
            );
        }

        if (!normalizedUrl.StartsWith("/", StringComparison.Ordinal)
            && Uri.TryCreate(normalizedUrl, UriKind.Absolute, out _))
        {
            throw new InvalidOperationException(
                $"Expected a relative URL path, but received an absolute URL: '{relativeUrl}'."
            );
        }

        var selectedEnvironment = ResolveEnvironmentName();
        var configuredBaseUri = ResolveConfiguredBaseUri(selectedEnvironment);
        var normalizedRelativeUrl = normalizedUrl.StartsWith("/", StringComparison.Ordinal)
            ? normalizedUrl
            : $"/{normalizedUrl}";

        return new Uri(configuredBaseUri, normalizedRelativeUrl).ToString();
    }

    public static string ResolveEnvironmentName()
    {
        var raw = Environment.GetEnvironmentVariable("TEST_TARGET_ENV");
        if (string.IsNullOrWhiteSpace(raw))
        {
            return "PROD";
        }

        var builder = new StringBuilder(raw.Length);
        foreach (var character in raw.Trim().ToUpperInvariant())
        {
            if (char.IsLetterOrDigit(character))
            {
                builder.Append(character);
                continue;
            }

            if (character is '-' or ' ' or '.')
            {
                builder.Append('_');
            }
        }

        if (builder.Length == 0)
        {
            throw new InvalidOperationException("TEST_TARGET_ENV is set but does not contain any valid letters or digits.");
        }

        return builder.ToString();
    }

    private static Uri ResolveConfiguredBaseUri(string environmentName)
    {
        var configuredBaseUrl = ResolveConfiguredBaseUrl(environmentName);
        if (!Uri.TryCreate(configuredBaseUrl, UriKind.Absolute, out var configuredBaseUri))
        {
            throw new InvalidOperationException(
                $"Configured base URL '{configuredBaseUrl}' for environment '{environmentName}' is not a valid absolute URI."
            );
        }

        return configuredBaseUri;
    }

    private static string ResolveConfiguredBaseUrl(string environmentName)
    {
        var environmentVariableName = $"VIEWPOINT_BASE_URL_{environmentName}";
        var environmentSpecific = ResolveOptionalEnvironmentVariable(environmentVariableName);
        if (!string.IsNullOrWhiteSpace(environmentSpecific))
        {
            return environmentSpecific;
        }

        if (environmentName.Equals("PROD", StringComparison.OrdinalIgnoreCase))
        {
            var legacy = ResolveOptionalEnvironmentVariable(LegacyProdBaseUrlVariableName);
            if (!string.IsNullOrWhiteSpace(legacy))
            {
                return legacy;
            }

            throw new InvalidOperationException(
                $"Neither '{environmentVariableName}' nor legacy '{LegacyProdBaseUrlVariableName}' is configured."
            );
        }

        throw new InvalidOperationException(
            $"Required environment variable '{environmentVariableName}' is not configured."
        );
    }
}
