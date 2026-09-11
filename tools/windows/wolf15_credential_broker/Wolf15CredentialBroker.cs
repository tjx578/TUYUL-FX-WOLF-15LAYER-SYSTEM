using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

internal static class Wolf15CredentialBroker
{
    private const string VaultSchema = "wolf15.lean_d0.executor_credentials.v1";
    private const string PipeSchema = "wolf15.runtime_credentials.v1";
    private const int MaximumEnvelopeBytes = 4096;

    private static int Main(string[] args)
    {
        byte[] cipher = null;
        byte[] plain = null;
        byte[] envelope = null;
        try
        {
            Dictionary<string, string> options = ParseArguments(args);
            SecurityIdentifier currentUserSid = ResolveCurrentUserSid(options);

            string vaultPath = Required(options, "vault");
            string expectedVaultSha256 = RequiredLowerHex(options, "vault-sha256", 64);
            string pipeName = Required(options, "pipe-name");
            string expectedExecutorId = Required(options, "executor-id");
            string expectedAccountReference = Required(options, "account-reference");
            string expectedBrokerServer = Required(options, "broker-server");
            string expectedVerificationKeyId = Required(options, "verification-key-id");
            string expectedAccountReferenceSha256 = RequiredLowerHex(options, "account-reference-sha256", 64);
            int timeoutMs = RequiredBoundedInteger(options, "timeout-ms", 100, 60000);

            ValidatePipeName(pipeName);
            if (!File.Exists(vaultPath))
                Fail("CREDENTIAL_VAULT_UNAVAILABLE");

            cipher = File.ReadAllBytes(vaultPath);
            if (!FixedTimeEquals(Hex(Sha256(cipher)), expectedVaultSha256))
                Fail("CREDENTIAL_VAULT_DIGEST_MISMATCH");

            plain = ProtectedData.Unprotect(cipher, null, DataProtectionScope.CurrentUser);
            Dictionary<string, object> vault = ParseExactVault(plain);
            RequireExactString(vault, "schema", VaultSchema, "CREDENTIAL_SCHEMA_INVALID");
            RequireExactString(vault, "executor_id", expectedExecutorId, "EXECUTOR_BINDING_MISMATCH");
            RequireExactString(vault, "account_id_reference", expectedAccountReference, "ACCOUNT_BINDING_MISMATCH");
            RequireExactString(vault, "broker_server", expectedBrokerServer, "BROKER_BINDING_MISMATCH");
            RequireExactString(vault, "verification_key_id", expectedVerificationKeyId, "KEY_ID_MISMATCH");
            RequireExactString(vault, "verification_key_type", "PER_EXECUTOR_HMAC", "VERIFICATION_KEY_TYPE_MISMATCH");

            string token = RequireLowerHexString(vault, "executor_token", 64, "CREDENTIAL_SCHEMA_INVALID");
            string verificationMaterial = RequireTaggedLowerHexString(
                vault,
                "verification_key",
                "hex:",
                64,
                "CREDENTIAL_SCHEMA_INVALID"
            );
            string actualAccountReferenceSha256 = Hex(Sha256(Encoding.UTF8.GetBytes(expectedAccountReference)));
            if (!FixedTimeEquals(actualAccountReferenceSha256, expectedAccountReferenceSha256))
                Fail("ACCOUNT_BINDING_MISMATCH");

            string canonical = "{\"schema\":\"" + PipeSchema +
                "\",\"executor_id\":\"" + expectedExecutorId +
                "\",\"account_reference_sha256\":\"" + expectedAccountReferenceSha256 +
                "\",\"verification_key_id\":\"" + expectedVerificationKeyId +
                "\",\"executor_token\":\"" + token +
                "\",\"verification_material\":\"" + verificationMaterial + "\"}";
            envelope = Encoding.UTF8.GetBytes(canonical);
            if (envelope.Length == 0 || envelope.Length > MaximumEnvelopeBytes)
                Fail("CREDENTIAL_ENVELOPE_OVERSIZE");

            ServeOnce(pipeName, envelope, timeoutMs, currentUserSid);
            return 0;
        }
        catch (ControlledFailure error)
        {
            Console.Error.WriteLine(error.ReasonCode);
            return 2;
        }
        catch (CryptographicException)
        {
            Console.Error.WriteLine("DPAPI_HELPER_REJECTED");
            return 3;
        }
        catch (UnauthorizedAccessException)
        {
            Console.Error.WriteLine("DPAPI_HELPER_REJECTED");
            return 3;
        }
        catch (Exception)
        {
            Console.Error.WriteLine("DPAPI_HELPER_REJECTED");
            return 3;
        }
        finally
        {
            Zero(cipher);
            Zero(plain);
            Zero(envelope);
        }
    }

    private static void ServeOnce(string pipeName, byte[] envelope, int timeoutMs, SecurityIdentifier sid)
    {
        PipeSecurity security = new PipeSecurity();
        security.SetAccessRuleProtection(true, false);
        security.AddAccessRule(new PipeAccessRule(sid, PipeAccessRights.ReadWrite, AccessControlType.Allow));

        using (NamedPipeServerStream server = new NamedPipeServerStream(
            pipeName,
            PipeDirection.Out,
            1,
            PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous | PipeOptions.WriteThrough,
            4096,
            4096,
            security
        ))
        {
            IAsyncResult pending = server.BeginWaitForConnection(null, null);
            if (!pending.AsyncWaitHandle.WaitOne(timeoutMs))
                Fail("CREDENTIAL_PIPE_TIMEOUT");
            server.EndWaitForConnection(pending);

            byte[] header = Encoding.ASCII.GetBytes(envelope.Length.ToString("D8", CultureInfo.InvariantCulture));
            try
            {
                server.Write(header, 0, header.Length);
                server.Write(envelope, 0, envelope.Length);
                server.Flush();
                server.WaitForPipeDrain();
            }
            finally
            {
                Zero(header);
            }
        }
    }

    private static Dictionary<string, object> ParseExactVault(byte[] plain)
    {
        string json = Encoding.UTF8.GetString(plain);
        Dictionary<string, object> result;
        try
        {
            result = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(json);
        }
        catch (Exception)
        {
            Fail("CREDENTIAL_SCHEMA_INVALID");
            return null;
        }
        finally
        {
            json = null;
        }

        string[] exactKeys = new[]
        {
            "schema", "executor_id", "account_id_reference", "broker_server",
            "executor_token", "verification_key_id", "verification_key_type",
            "verification_key", "issued_at_utc", "expires_at_utc"
        };
        if (result == null || result.Count != exactKeys.Length)
            Fail("CREDENTIAL_SCHEMA_INVALID");
        foreach (string key in exactKeys)
            if (!result.ContainsKey(key))
                Fail("CREDENTIAL_SCHEMA_INVALID");
        if (result["issued_at_utc"] == null || !(result["issued_at_utc"] is string))
            Fail("CREDENTIAL_SCHEMA_INVALID");
        if (result["expires_at_utc"] != null)
            Fail("CREDENTIAL_SCHEMA_INVALID");
        return result;
    }

    private static Dictionary<string, string> ParseArguments(string[] args)
    {
        if (args == null || args.Length == 0 || args.Length % 2 != 0)
            Fail("ARGUMENT_CONTRACT_INVALID");
        Dictionary<string, string> options = new Dictionary<string, string>(StringComparer.Ordinal);
        for (int index = 0; index < args.Length; index += 2)
        {
            string name = args[index];
            if (name == null || !name.StartsWith("--", StringComparison.Ordinal) || name.Length < 3)
                Fail("ARGUMENT_CONTRACT_INVALID");
            name = name.Substring(2);
            if (options.ContainsKey(name))
                Fail("ARGUMENT_CONTRACT_INVALID");
            options.Add(name, args[index + 1]);
        }
        if (options.Count != 9 && options.Count != 10)
            Fail("ARGUMENT_CONTRACT_INVALID");
        if (options.Count == 10 && !options.ContainsKey("expected-user-sid"))
            Fail("ARGUMENT_CONTRACT_INVALID");
        return options;
    }

    private static string Required(Dictionary<string, string> options, string name)
    {
        string value;
        if (!options.TryGetValue(name, out value) || String.IsNullOrEmpty(value))
            Fail("ARGUMENT_CONTRACT_INVALID");
        return value;
    }

    private static int RequiredBoundedInteger(Dictionary<string, string> options, string name, int minimum, int maximum)
    {
        int value;
        if (!Int32.TryParse(Required(options, name), NumberStyles.None, CultureInfo.InvariantCulture, out value) ||
            value < minimum || value > maximum)
            Fail("ARGUMENT_CONTRACT_INVALID");
        return value;
    }

    private static string RequiredLowerHex(Dictionary<string, string> options, string name, int length)
    {
        string value = Required(options, name);
        if (!IsLowerHex(value, length))
            Fail("ARGUMENT_CONTRACT_INVALID");
        return value;
    }

    // The security boundary is DPAPI CurrentUser plus a pipe ACL restricted to the
    // running account's SID. A literal username in canonical source adds no boundary
    // and ties the artifact to one workstation, so the SID is resolved at runtime.
    // --expected-user-sid is an optional, explicit, non-secret extra binding.
    private static SecurityIdentifier ResolveCurrentUserSid(Dictionary<string, string> options)
    {
        WindowsIdentity identity = WindowsIdentity.GetCurrent();
        SecurityIdentifier sid = identity == null ? null : identity.User;
        if (sid == null)
            Fail("WINDOWS_IDENTITY_UNAVAILABLE");

        string expected;
        if (options.TryGetValue("expected-user-sid", out expected))
        {
            if (String.IsNullOrEmpty(expected) || !IsWindowsSid(expected))
                Fail("ARGUMENT_CONTRACT_INVALID");
            if (!String.Equals(sid.Value, expected, StringComparison.OrdinalIgnoreCase))
                Fail("WRONG_WINDOWS_USER");
        }
        return sid;
    }

    private static bool IsWindowsSid(string value)
    {
        if (value == null || value.Length < 8 || value.Length > 184)
            return false;
        if (!value.StartsWith("S-1-", StringComparison.Ordinal))
            return false;
        foreach (char character in value)
            if (!((character >= '0' && character <= '9') || character == '-' || character == 'S'))
                return false;
        try
        {
            new SecurityIdentifier(value);
        }
        catch (ArgumentException)
        {
            return false;
        }
        return true;
    }

    private static void ValidatePipeName(string value)
    {
        if (!value.StartsWith("wolf15-lean-d0-", StringComparison.Ordinal) || value.Length > 100)
            Fail("ARGUMENT_CONTRACT_INVALID");
        foreach (char character in value)
            if (!((character >= 'a' && character <= 'z') ||
                  (character >= '0' && character <= '9') || character == '-'))
                Fail("ARGUMENT_CONTRACT_INVALID");
    }

    private static void RequireExactString(
        Dictionary<string, object> values,
        string name,
        string expected,
        string reasonCode
    )
    {
        object raw;
        if (!values.TryGetValue(name, out raw) || !(raw is string) ||
            !String.Equals((string)raw, expected, StringComparison.Ordinal))
            Fail(reasonCode);
    }

    private static string RequireLowerHexString(
        Dictionary<string, object> values,
        string name,
        int length,
        string reasonCode
    )
    {
        object raw;
        if (!values.TryGetValue(name, out raw) || !(raw is string) || !IsLowerHex((string)raw, length))
            Fail(reasonCode);
        return (string)raw;
    }

    private static string RequireTaggedLowerHexString(
        Dictionary<string, object> values,
        string name,
        string prefix,
        int hexLength,
        string reasonCode
    )
    {
        object raw;
        if (!values.TryGetValue(name, out raw) || !(raw is string))
            Fail(reasonCode);
        string value = (string)raw;
        if (!value.StartsWith(prefix, StringComparison.Ordinal) ||
            !IsLowerHex(value.Substring(prefix.Length), hexLength))
            Fail(reasonCode);
        return value;
    }

    private static bool IsLowerHex(string value, int exactLength)
    {
        if (value == null || value.Length != exactLength)
            return false;
        foreach (char character in value)
            if (!((character >= '0' && character <= '9') || (character >= 'a' && character <= 'f')))
                return false;
        return true;
    }

    private static byte[] Sha256(byte[] value)
    {
        using (SHA256 algorithm = SHA256.Create())
            return algorithm.ComputeHash(value);
    }

    private static string Hex(byte[] value)
    {
        StringBuilder result = new StringBuilder(value.Length * 2);
        foreach (byte item in value)
            result.Append(item.ToString("x2", CultureInfo.InvariantCulture));
        return result.ToString();
    }

    private static bool FixedTimeEquals(string left, string right)
    {
        if (left == null || right == null || left.Length != right.Length)
            return false;
        int difference = 0;
        for (int index = 0; index < left.Length; index++)
            difference |= left[index] ^ right[index];
        return difference == 0;
    }

    private static void Zero(byte[] value)
    {
        if (value != null)
            Array.Clear(value, 0, value.Length);
    }

    private static void Fail(string reasonCode)
    {
        throw new ControlledFailure(reasonCode);
    }

    private sealed class ControlledFailure : Exception
    {
        internal readonly string ReasonCode;
        internal ControlledFailure(string reasonCode) { ReasonCode = reasonCode; }
    }
}
