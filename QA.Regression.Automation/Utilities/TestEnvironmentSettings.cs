using System.Text;

namespace QA.Regression.Automation.Utilities;

public static class TestEnvironmentSettings
{
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

    public static string ResolveUrlForEnvironment(string defaultUrl)
    {
        var selectedEnvironment = ResolveEnvironmentName();
        var configuredBaseUrl = ResolveConfiguredBaseUrl(selectedEnvironment);

        if (string.IsNullOrWhiteSpace(configuredBaseUrl))
        {
            if (EnvironmentWasExplicitlySelected() && !selectedEnvironment.Equals("PROD", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    $"TEST_TARGET_ENV is set to '{selectedEnvironment}', but VIEWPOINT_BASE_URL_{selectedEnvironment} is not configured."
                );
            }

            return defaultUrl;
        }

        if (!Uri.TryCreate(configuredBaseUrl, UriKind.Absolute, out var configuredBaseUri))
        {
            throw new InvalidOperationException(
                $"Configured base URL '{configuredBaseUrl}' for environment '{selectedEnvironment}' is not a valid absolute URI."
            );
        }

        if (!Uri.TryCreate(defaultUrl, UriKind.Absolute, out var defaultUri))
        {
            return configuredBaseUri.ToString();
        }

        var resolved = new UriBuilder(defaultUri)
        {
            Scheme = configuredBaseUri.Scheme,
            Host = configuredBaseUri.Host,
            Port = configuredBaseUri.IsDefaultPort ? -1 : configuredBaseUri.Port,
        };

        return resolved.Uri.ToString();
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

    private static bool EnvironmentWasExplicitlySelected()
    {
        return !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("TEST_TARGET_ENV"));
    }

    private static string? ResolveConfiguredBaseUrl(string environmentName)
    {
        var environmentSpecific = ResolveOptionalEnvironmentVariable($"VIEWPOINT_BASE_URL_{environmentName}");
        if (!string.IsNullOrWhiteSpace(environmentSpecific))
        {
            return environmentSpecific;
        }

        if (environmentName.Equals("PROD", StringComparison.OrdinalIgnoreCase))
        {
            var legacy = ResolveOptionalEnvironmentVariable("VIEWPOINT_BASE_URL");
            if (!string.IsNullOrWhiteSpace(legacy))
            {
                return legacy;
            }
        }

        return null;
    }
}
