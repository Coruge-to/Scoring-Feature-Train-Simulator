using System;
using System.Text;
using TSScoringPlugin.DataPlane;

// PID-D3 test helper for the live-chain scripts (Test-HudLinkE4.ps1, Test-AppProcessE3.ps1): it plays the Current sender's DISCOVERY half for a stand-in BVE
// process - the shared TelemetryDirectoryReader resolves the managed application's Directory endpoint exactly as the real sender does, and the datagram is
// wrapped in Envelope v1. The script sends the returned bytes itself (this file touches no socket). Nothing is returned while the Directory is unresolved,
// not READY, mismatched or lacks ENVELOPE_V1: the chain must not be fed through any other route.
public static class DataPlaneFeedFixture
{
    public static byte[] Prepare(int bvePid, uint messageType, string text, out int port, out string reason, out uint capabilities)
    {
        port = 0;
        capabilities = 0U;
        TelemetryEndpoint endpoint;
        if (!TelemetryDirectoryReader.TryResolve(bvePid, out endpoint, out reason)) return null;
        capabilities = endpoint.Capabilities;
        if ((endpoint.Capabilities & 0x1U) == 0U) { reason = "capability-missing"; return null; }
        port = (int)endpoint.Port;
        return DataPlaneProtocol.EncodeEnvelope(messageType, (uint)bvePid, (uint)bvePid, endpoint.Generation, endpoint.AppInstance, endpoint.Token, new byte[16], Encoding.UTF8.GetBytes(text));
    }
}
