using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

internal static class Wolf15CredentialBroker
{
    private const string VaultSchema = "wolf15.lean_d0.executor_credentials.v1";
    private const string RuntimeSchema = "wolf15.runtime_credentials.v1";
    private const string PipePrefix = "wolf15-lean-d0-";
    private const int MaximumPipeInstances = 1;

    private sealed class BrokerOptions
    {
        public string VaultPath = string.Empty;
        public string ExpectedVaultSha256 = string.Empty;
        public string PipeName = string.Empty;
        public string ExpectedExecutorId = string.Empty;
        public string ExpectedAccountReference = string.Empty;
        public string ExpectedBrokerServer = string.Empty;
        public string ExpectedVerificationKeyId = string.Empty;
        public string ExpectedAccountReferenceSha256 = string.Empty;
        public int TimeoutMs;
        public string ServeMode = "once";
        public string? ExpectedUserSid;
    }

    private sealed class VaultDocument
    {
        public string schema { get; set; } = string.Empty;
        public string executor_id { get; set; } = string.Empty;
        public string account_reference { get; set; } = string.Empty;
        public string broker_server { get; set; } = string.Empty;
        public string verification_key_id { get; set; } = string.Empty;
        public string base_url { get; set; } = string.Empty;
        public string authorization_token { get; set; } = string.Empty;
        public string command_verification_key { get; set; } = string.Empty;
    }

    private sealed class RuntimeEnvelope
    {
        public string schema { get; set; } = RuntimeSchema;
        public string base_url { get; set; } = string.Empty;
        public string authorization_token { get; set; } = string.Empty;
        public string command_verification_key { get; set; } = string.Empty;
        public string executor_id { get; set; } = string.Empty;
        public string account_reference { get; set; } = string.Empty;
        public string broker_server { get; set; } = string.Empty;
        public string verification_key_id { get; set; } = string.Empty;
    }

    private static int Main(string[] args)
    {
        try
        {
            BrokerOptions options = ParseOptions(args);
            ValidatePipeName(options.PipeName);
            ValidateCurrentUser(options.ExpectedUserSid);

            if (string.Equals(options.ServeMode, "persistent", StringComparison.OrdinalIgnoreCase))
            {
                return RunPersistent(options);
            }

            return RunOnce(options);
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(SanitizeFailure(exception));
            return 2;
        }
    }

    private static int RunOnce(BrokerOptions options)
    {
        return ServeSingleConnection(options) ? 0 : 2;
    }

    private static int RunPersistent(BrokerOptions options)
    {
        Console.WriteLine("BROKER_READY mode=persistent");
        Console.Out.Flush();

        while (true)
        {
            try
            {
                ServeSingleConnection(options);
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine(SanitizeFailure(exception));
                Console.Error.Flush();
                Thread.Sleep(250);
            }
        }
    }

    private static bool ServeSingleConnection(BrokerOptions options)
    {
        byte[]? vaultCiphertext = null;
        byte[]? vaultPlaintext = null;
        byte[]? runtimeBytes = null;

        try
        {
            vaultCiphertext = File.ReadAllBytes(options.VaultPath);
            VerifySha256(vaultCiphertext, options.ExpectedVaultSha256);

            vaultPlaintext = ProtectedData.Unprotect(
                vaultCiphertext,
                null,
                DataProtectionScope.CurrentUser);

            string vaultJson = Encoding.UTF8.GetString(vaultPlaintext);
            JavaScriptSerializer serializer = new JavaScriptSerializer();
            VaultDocument? vault = serializer.Deserialize<VaultDocument>(vaultJson);

            if (vault == null)
            {
                throw new InvalidDataException("VAULT_DESERIALIZATION_FAILED");
            }

            ValidateVault(vault, options);

            RuntimeEnvelope runtime = new RuntimeEnvelope
            {
                base_url = vault.base_url,
                authorization_token = vault.authorization_token,
                command_verification_key = vault.command_verification_key,
                executor_id = vault.executor_id,
                account_reference = vault.account_reference,
                broker_server = vault.broker_server,
                verification_key_id = vault.verification_key_id,
            };

            string runtimeJson = serializer.Serialize(runtime);
            runtimeBytes = Encoding.UTF8.GetBytes(runtimeJson);

            PipeSecurity pipeSecurity = BuildCurrentUserOnlyPipeSecurity();

            using (NamedPipeServerStream pipe = new NamedPipeServerStream(
                options.PipeName,
                PipeDirection.Out,
                MaximumPipeInstances,
                PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous,
                4096,
                4096,
                pipeSecurity))
            {
                IAsyncResult waitResult = pipe.BeginWaitForConnection(null, null);

                if (!waitResult.AsyncWaitHandle.WaitOne(options.TimeoutMs))
                {
                    try
                    {
                        pipe.Dispose();
                    }
                    catch
                    {
                    }

                    throw new TimeoutException("CREDENTIAL_PIPE_TIMEOUT");
                }

                pipe.EndWaitForConnection(waitResult);
                pipe.Write(runtimeBytes, 0, runtimeBytes.Length);
                pipe.Flush();
                pipe.WaitForPipeDrain();
            }

            if (string.Equals(options.ServeMode, "persistent", StringComparison.OrdinalIgnoreCase))
            {
                Console.WriteLine("CREDENTIAL_HANDOFF_OK mode=persistent");
            }
            else
            {
                Console.WriteLine("CREDENTIAL_HANDOFF_OK mode=once");
            }

            Console.Out.Flush();
            return true;
        }
        finally
        {
            ZeroBuffer(runtimeBytes);
            ZeroBuffer(vaultPlaintext);
            ZeroBuffer(vaultCiphertext);
        }
    }

    private static BrokerOptions ParseOptions(string[] args)
    {
        if (args.Length == 0 || args.Length % 2 != 0)
        {
            throw new ArgumentException("ARGUMENT_CONTRACT_INVALID");
        }

        Dictionary<string, string> options = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        for (int index = 0; index < args.Length; index += 2)
        {
            string key = args[index];
            string value = args[index + 1];

            if (!key.StartsWith("--", StringComparison.Ordinal))
            {
                throw new ArgumentException("ARGUMENT_CONTRACT_INVALID");
            }

            options[key.Substring(2)] = value;
        }

        HashSet<string> allowed = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "vault",
            "vault-sha256",
            "pipe-name",
            "executor-id",
            "account-reference",
            "broker-server",
            "verification-key-id",
            "account-reference-sha256",
            "timeout-ms",
            "serve-mode",
            "expected-user-sid",
        };

        foreach (string key in options.Keys)
        {
            if (!allowed.Contains(key))
            {
                throw new ArgumentException("ARGUMENT_CONTRACT_INVALID");
            }
        }

        BrokerOptions result = new BrokerOptions
        {
            VaultPath = Required(options, "vault"),
            ExpectedVaultSha256 = RequiredLowerHex(options, "vault-sha256", 64),
            PipeName = Required(options, "pipe-name"),
            ExpectedExecutorId = Required(options, "executor-id"),
            ExpectedAccountReference = Required(options, "account-reference"),
            ExpectedBrokerServer = Required(options, "broker-server"),
            ExpectedVerificationKeyId = Required(options, "verification-key-id"),
            ExpectedAccountReferenceSha256 = RequiredLowerHex(options, "account-reference-sha256", 64),
            TimeoutMs = RequiredBoundedInteger(options, "timeout-ms", 100, 60000),
            ServeMode = OptionalServeMode(options),
            ExpectedUserSid = Optional(options, "expected-user-sid"),
        };

        return result;
    }

    private static string OptionalServeMode(Dictionary<string, string> options)
    {
        string value = Optional(options, "serve-mode") ?? "once";

        if (!string.Equals(value, "once", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(value, "persistent", StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("ARGUMENT_CONTRACT_INVALID");
        }

        return value.ToLowerInvariant();
    }

    private static string Required(Dictionary<string, string> options, string key)
    {
        string? value = Optional(options, key);

        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException("ARGUMENT_CONTRACT_INVALID");
        }

        return value;
    }

    private static string? Optional(Dictionary<string, string> options, string key)
    {
        return options.TryGetValue(key, out string? value) ? value : null;
    }

    private static string RequiredLowerHex(Dictionary<string, string> options, string key, int length)
    {
        string value = Required(options, key).Trim().ToLowerInvariant();

        if (value.Length != length || value.Any(character => !Uri.IsHexDigit(character)))
        {
            throw new ArgumentException("ARGUMENT_CONTRACT_INVALID");
        }

        return value;
    }

    private static int RequiredBoundedInteger(
        Dictionary<string, string> options,
        string key,
        int minimum,
        int maximum)
    {
        string value = Required(options, key);

        if (!int.TryParse(value, out int parsed) || parsed < minimum || parsed > maximum)
        {
            throw new ArgumentException("ARGUMENT_CONTRACT_INVALID");
        }

        return parsed;
    }

    private static void ValidatePipeName(string pipeName)
    {
        if (!pipeName.StartsWith(PipePrefix, StringComparison.Ordinal) ||
            pipeName.Any(character => !(char.IsLower(character) || char.IsDigit(character) || character == '-')))
        {
            throw new ArgumentException("PIPE_NAME_INVALID");
        }
    }

    private static void ValidateCurrentUser(string? expectedUserSid)
    {
        WindowsIdentity identity = WindowsIdentity.GetCurrent();
        string currentSid = identity.User?.Value ?? string.Empty;

        if (string.IsNullOrWhiteSpace(currentSid))
        {
            throw new InvalidOperationException("CURRENT_USER_SID_UNAVAILABLE");
        }

        if (!string.IsNullOrWhiteSpace(expectedUserSid) &&
            !string.Equals(currentSid, expectedUserSid, StringComparison.Ordinal))
        {
            throw new UnauthorizedAccessException("CURRENT_USER_SID_MISMATCH");
        }
    }

    private static PipeSecurity BuildCurrentUserOnlyPipeSecurity()
    {
        WindowsIdentity identity = WindowsIdentity.GetCurrent();
        SecurityIdentifier? sid = identity.User;

        if (sid == null)
        {
            throw new InvalidOperationException("CURRENT_USER_SID_UNAVAILABLE");
        }

        PipeSecurity security = new PipeSecurity();
        security.SetAccessRuleProtection(true, false);
        security.AddAccessRule(new PipeAccessRule(
            sid,
            PipeAccessRights.FullControl,
            AccessControlType.Allow));
        security.SetOwner(sid);

        return security;
    }

    private static void VerifySha256(byte[] content, string expectedSha256)
    {
        using (SHA256 sha = SHA256.Create())
        {
            string actual = BitConverter.ToString(sha.ComputeHash(content)).Replace("-", string.Empty).ToLowerInvariant();

            if (!string.Equals(actual, expectedSha256, StringComparison.Ordinal))
            {
                throw new InvalidDataException("VAULT_SHA256_MISMATCH");
            }
        }
    }

    private static void ValidateVault(VaultDocument vault, BrokerOptions options)
    {
        if (!string.Equals(vault.schema, VaultSchema, StringComparison.Ordinal))
        {
            throw new InvalidDataException("VAULT_SCHEMA_INVALID");
        }

        if (!string.Equals(vault.executor_id, options.ExpectedExecutorId, StringComparison.Ordinal))
        {
            throw new InvalidDataException("EXECUTOR_BINDING_INVALID");
        }

        if (!string.Equals(vault.account_reference, options.ExpectedAccountReference, StringComparison.Ordinal))
        {
            throw new InvalidDataException("ACCOUNT_REFERENCE_BINDING_INVALID");
        }

        if (!string.Equals(vault.broker_server, options.ExpectedBrokerServer, StringComparison.Ordinal))
        {
            throw new InvalidDataException("BROKER_SERVER_BINDING_INVALID");
        }

        if (!string.Equals(vault.verification_key_id, options.ExpectedVerificationKeyId, StringComparison.Ordinal))
        {
            throw new InvalidDataException("VERIFICATION_KEY_BINDING_INVALID");
        }

        string accountReferenceSha256 = Sha256Hex(vault.account_reference);
        if (!string.Equals(accountReferenceSha256, options.ExpectedAccountReferenceSha256, StringComparison.Ordinal))
        {
            throw new InvalidDataException("ACCOUNT_REFERENCE_SHA256_INVALID");
        }

        if (string.IsNullOrWhiteSpace(vault.base_url) ||
            string.IsNullOrWhiteSpace(vault.authorization_token) ||
            string.IsNullOrWhiteSpace(vault.command_verification_key))
        {
            throw new InvalidDataException("VAULT_REQUIRED_SECRET_MISSING");
        }
    }

    private static string Sha256Hex(string value)
    {
        using (SHA256 sha = SHA256.Create())
        {
            byte[] bytes = Encoding.UTF8.GetBytes(value);
            try
            {
                return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", string.Empty).ToLowerInvariant();
            }
            finally
            {
                ZeroBuffer(bytes);
            }
        }
    }

    private static void ZeroBuffer(byte[]? buffer)
    {
        if (buffer == null)
        {
            return;
        }

        Array.Clear(buffer, 0, buffer.Length);
    }

    private static string SanitizeFailure(Exception exception)
    {
        string message = exception.Message ?? exception.GetType().Name;
        return message.Replace(Environment.NewLine, " ").Replace("\r", " ").Replace("\n", " ");
    }
}
