using System;

namespace TSScoringPlugin.Handshake
{
    internal static class F11CloseProtocol
    {
        private const string Prefix = "Local\\TSScoringPlugin.v1.";
        internal const int RestoreTimeoutMs = 2000;

        internal static string FullscreenActive(int processId)
        {
            return Prefix + processId + ".F11.FullscreenActive";
        }

        internal static string RestoreRequested(int processId)
        {
            return Prefix + processId + ".F11.RestoreRequested";
        }

        internal static string RestoreCompleted(int processId)
        {
            return Prefix + processId + ".F11.RestoreCompleted";
        }
    }
}
