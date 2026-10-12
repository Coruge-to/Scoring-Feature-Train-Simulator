using System;
using System.IO.MemoryMappedFiles;
using System.Text;
using System.Threading;

namespace TSScoringPlugin.Handshake
{
    [Flags]
    internal enum AppDirectoryFlags : uint
    {
        None = 0,
        InstancePublished = 1u << 0,
        ProcessStarted = 1u << 1,
        ReadyAccepted = 1u << 2,
        Withdrawing = 1u << 3,
        Closed = 1u << 4
    }

    internal sealed class AppDirectoryPublisher : IDisposable
    {
        internal const uint Magic = 0x44415354u;
        internal const uint Version = 1u;
        internal const int BlockSize = 80;
        internal const int InstanceLength = 32;

        private readonly int bveProcessId;
        private readonly MemoryMappedFile mapping;
        private readonly MemoryMappedViewAccessor view;
        private uint sequence;
        private uint changeCount;
        private AppDirectoryFlags flags;
        private string instance;
        private int appProcessId;
        private bool disposed;

        private AppDirectoryPublisher(int bveProcessId, MemoryMappedFile mapping, MemoryMappedViewAccessor view)
        {
            this.bveProcessId = bveProcessId;
            this.mapping = mapping;
            this.view = view;
            instance = string.Empty;
            PublishCore(AppDirectoryFlags.Closed, string.Empty, 0, true);
        }

        internal static string ObjectName(int bveProcessId)
        {
            if (bveProcessId <= 0) throw new ArgumentOutOfRangeException("bveProcessId");
            return AppObjectNames.Prefix + bveProcessId + ".AppDirectory";
        }

        internal static AppDirectoryPublisher Create(int bveProcessId)
        {
            string name = ObjectName(bveProcessId);
            MemoryMappedFile mapping = MemoryMappedFile.CreateNew(name, BlockSize, MemoryMappedFileAccess.ReadWrite);
            try
            {
                MemoryMappedViewAccessor view = mapping.CreateViewAccessor(0, BlockSize, MemoryMappedFileAccess.ReadWrite);
                return new AppDirectoryPublisher(bveProcessId, mapping, view);
            }
            catch
            {
                mapping.Dispose();
                throw;
            }
        }

        internal void PublishInstance(string value)
        {
            ValidateInstance(value);
            PublishCore(AppDirectoryFlags.InstancePublished, value, 0, false);
        }

        internal void PublishProcessStarted(int processId)
        {
            if (processId <= 0) throw new ArgumentOutOfRangeException("processId");
            EnsureInstance();
            PublishCore(AppDirectoryFlags.InstancePublished | AppDirectoryFlags.ProcessStarted, instance, processId, false);
        }

        internal void PublishReadyAccepted()
        {
            EnsureInstance();
            if (appProcessId <= 0) throw new InvalidOperationException("ProcessStarted must be published before ReadyAccepted.");
            PublishCore(AppDirectoryFlags.InstancePublished | AppDirectoryFlags.ProcessStarted | AppDirectoryFlags.ReadyAccepted, instance, appProcessId, false);
        }

        internal void PublishWithdrawing()
        {
            EnsureInstance();
            PublishCore(flags | AppDirectoryFlags.Withdrawing, instance, appProcessId, false);
        }

        internal void PublishClosed()
        {
            PublishCore(AppDirectoryFlags.Closed, string.Empty, 0, false);
        }

        private void PublishCore(AppDirectoryFlags nextFlags, string nextInstance, int nextAppProcessId, bool force)
        {
            ThrowIfDisposed();
            if (!force && flags == nextFlags && instance == nextInstance && appProcessId == nextAppProcessId) return;

            uint odd = unchecked(sequence + 1u);
            if ((odd & 1u) == 0u) odd = unchecked(odd + 1u);
            uint even = unchecked(odd + 1u);
            changeCount = unchecked(changeCount + 1u);

            view.Write(16, odd);
            Thread.MemoryBarrier();
            view.Write(0, Magic);
            view.Write(4, Version);
            view.Write(8, (uint)BlockSize);
            view.Write(12, (uint)bveProcessId);
            view.Write(20, (uint)nextFlags);
            WriteInstance(nextInstance);
            view.Write(56, (uint)nextAppProcessId);
            view.Write(60, changeCount);
            view.Write(64, 0u);
            view.Write(68, 0u);
            view.Write(72, 0u);
            Thread.MemoryBarrier();
            view.Write(76, even);
            Thread.MemoryBarrier();
            view.Write(16, even);
            view.Flush();

            sequence = even;
            flags = nextFlags;
            instance = nextInstance;
            appProcessId = nextAppProcessId;
        }

        private void WriteInstance(string value)
        {
            byte[] bytes = new byte[InstanceLength];
            if (!string.IsNullOrEmpty(value)) Encoding.ASCII.GetBytes(value, 0, value.Length, bytes, 0);
            view.WriteArray(24, bytes, 0, bytes.Length);
        }

        private static void ValidateInstance(string value)
        {
            if (value == null || value.Length != InstanceLength) throw new ArgumentException("AppInstance must be 32 lower-case hexadecimal characters.", "value");
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) throw new ArgumentException("AppInstance must be 32 lower-case hexadecimal characters.", "value");
            }
        }

        private void EnsureInstance()
        {
            ThrowIfDisposed();
            if (string.IsNullOrEmpty(instance)) throw new InvalidOperationException("InstancePublished must be published first.");
        }

        private void ThrowIfDisposed()
        {
            if (disposed) throw new ObjectDisposedException("AppDirectoryPublisher");
        }

        public void Dispose()
        {
            if (disposed) return;
            try { PublishClosed(); } catch { }
            disposed = true;
            try { view.Dispose(); } finally { mapping.Dispose(); }
        }
    }
}
