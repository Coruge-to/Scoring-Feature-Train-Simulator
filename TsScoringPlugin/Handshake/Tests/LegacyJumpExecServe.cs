using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net;
using System.Reflection;
using System.Text;
using TSScoringPlugin.DataPlane;
using TSScoringPlugin.Telemetry;

// ============================================================================================================================================
// PHASE PID-D4 / LEGACY JUMP LJX-1 - one served plane for the interop test of the managed application (TEST CODE ONLY, never part of the product DLL).
//
// The plane is the PRODUCT plane (real named mapping of a synthetic BVE process id, real loopback datagram port, the dedicated worker) with the execution switched on or off,
// the product executor and Tick runner, the real telemetry session over a fake Legacy API and a fake host, and - as the completion sender - the REAL sink of the product
// (LegacyDataPlaneSink over the Current routing core in managed mode, a real loopback datagram socket) addressed to the Telemetry endpoint of the managed application, which the
// test hands in (instance, process id, port, generation, token). Nothing here touches BVE, AtsEX or a fixed port.
// ============================================================================================================================================
namespace TsScoringLegacyTelemetryTests
{
    public sealed class ServeExec : IDisposable
    {
        private readonly Ctx ctx = new Ctx("serve");
        private LxRig rig;
        private LegacyDataPlaneSink sink;
        private bool disposed;

        public static ServeExec Open(Assembly product, string runId, bool execution, string instance, int appPid, int telemetryPort, int telemetryGeneration, string telemetryTokenHex)
        {
            Pr.Load(product);
            Env.Init(runId);
            ServeExec s = new ServeExec();
            s.Build(execution, instance, appPid, telemetryPort, telemetryGeneration, telemetryTokenHex);
            return s;
        }

        private static byte[] FromHex(string hex)
        {
            byte[] b = new byte[hex.Length / 2];
            for (int i = 0; i < b.Length; i++) b[i] = Byte.Parse(hex.Substring(2 * i, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
            return b;
        }

        private void Build(bool execution, string instance, int appPid, int telemetryPort, int telemetryGeneration, string telemetryTokenHex)
        {
            byte[] token = FromHex(telemetryTokenHex);
            LxOpts o = new LxOpts();
            o.Enabled = execution;
            o.TtlMs = execution ? 5000 : 0;
            o.Owner = delegate (int pid)
            {
                return new TelemetryEndpoint((UInt32)pid, instance, (UInt32)appPid, (UInt32)telemetryPort, (UInt32)telemetryGeneration, token, 5U, 7U);
            };
            o.SenderFactory = delegate (LxRig r)
            {
                DpProbe probe = new DpProbe();
                probe.Enabled = true;
                DpClock clock = new DpClock();
                Func<long> now = delegate { return r.Mono; };
                LegacyUdpTransport transport = new LegacyUdpTransport();
                CurrentModeLatch latch = new CurrentModeLatch(probe, now, CurrentModeLatch.DefaultHoldOffMs, delegate { });
                CurrentTelemetryRouter router = new CurrentTelemetryRouter(r.R.Pid, transport, new IPEndPoint(IPAddress.Loopback, 9), r.R.Src, latch, now, delegate { });
                sink = new LegacyDataPlaneSink(router, transport, delegate { });
                return sink;
            };
            rig = LxRig.Make(ctx, o);
        }

        private static string Esc(string s) { return s.Replace("\\", "\\\\").Replace("\"", "\\\""); }

        public string Status()
        {
            DirRead d = DirView.Poll(rig.R.Name);
            StringBuilder sb = new StringBuilder();
            sb.Append("{\"ok\":true,\"bve_pid\":").Append(rig.R.Pid).Append(",\"name\":\"").Append(Esc(rig.R.Name)).Append("\",\"port\":").Append(d.Port)
              .Append(",\"generation\":").Append(d.Generation).Append(",\"caps\":").Append(d.Caps).Append(",\"state\":").Append(d.State)
              .Append(",\"jump_available\":").Append((bool)Pr.Get(rig.P.Raw, "JumpAvailable") ? "true" : "false").Append("}");
            return sb.ToString();
        }

        /// <summary>One logical Tick of the host (claim, execute, row, completion). Returns the host calls of this Tick and the counters.</summary>
        public string Tick()
        {
            int before = rig.Host.ApiCalls;
            rig.Tick(16);
            string[] calls = rig.Host.CallsSnapshot();
            StringBuilder sb = new StringBuilder();
            sb.Append("{\"ok\":true,\"host\":[");
            for (int i = before; i < calls.Length; i++)
            {
                if (i > before) sb.Append(',');
                sb.Append('"').Append(Esc(calls[i])).Append('"');
            }
            sb.Append("],\"jump_count\":").Append(Convert.ToInt32(Pr.Get(rig.Session, "Discontinuities")))
              .Append(",\"claimed\":").Append(rig.Counter("claimed")).Append(",\"completed\":").Append(rig.Counter("completed"))
              .Append(",\"abandoned\":").Append(rig.Counter("abandoned")).Append(",\"failed\":").Append(rig.Counter("failed")).Append("}");
            return sb.ToString();
        }

        public string Finish()
        {
            Dispose();
            return "{\"ok\":true}";
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            try { if (rig != null) rig.Dispose(); } catch { }
            try { if (sink != null) sink.Close(); } catch { }
            try { ctx.ReleaseAll(); } catch { }
        }
    }
}
