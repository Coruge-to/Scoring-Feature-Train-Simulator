#include "stdafx.h"
#include "atsplugin.h"
#include <winsock2.h>
#include <ws2tcpip.h>
#include <stdio.h>

// UDP通信用のライブラリをリンク
#pragma comment(lib, "ws2_32.lib")

// --- 通信用変数 ---
SOCKET udpSocket = INVALID_SOCKET;
struct sockaddr_in destAddr;

// --- 運転操作のパススルー（通過）用変数 ---
ATS_HANDLES g_output;
int g_powerNotch = 0;
int g_brakeNotch = 0;
int g_reverser = 0;

BOOL APIENTRY DllMain(HANDLE hModule, DWORD ul_reason_for_call, LPVOID lpReserved)
{
    return TRUE; // DLLが読み込まれた時の処理（今回は何もしない）
}

ATS_API void WINAPI Load()
{
    // BVE読込時：UDPソケットの準備
    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);
    udpSocket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    destAddr.sin_family = AF_INET;
    destAddr.sin_port = htons(54321); // Python側で待ち受けるポート番号
    inet_pton(AF_INET, "127.0.0.1", &destAddr.sin_addr); // 自分のPC（ローカルホスト）宛
}

ATS_API void WINAPI Dispose()
{
    // BVE終了時：ソケットのお片付け
    if (udpSocket != INVALID_SOCKET) {
        closesocket(udpSocket);
        udpSocket = INVALID_SOCKET;
    }
    WSACleanup();
}

ATS_API int WINAPI GetPluginVersion()
{
    return ATS_VERSION;
}

// 毎フレーム（約1/60秒ごと）呼ばれる心臓部
ATS_API ATS_HANDLES WINAPI Elapse(ATS_VEHICLESTATE vehicleState, int* panel, int* sound)
{
    // 1. Pythonへデータを送信（投げっぱなし）
    if (udpSocket != INVALID_SOCKET) {
        char buffer[128];
        // 速度と時間をカンマ区切りの文字列にする
        sprintf_s(buffer, sizeof(buffer), "SPEED:%.2f,TIME:%d", vehicleState.Speed, vehicleState.Time);
        sendto(udpSocket, buffer, strlen(buffer), 0, (SOCKADDR*)&destAddr, sizeof(destAddr));
    }

    // 2. プレイヤーの操作をそのままBVEに返す（干渉しないため）
    g_output.Power = g_powerNotch;
    g_output.Brake = g_brakeNotch;
    g_output.Reverser = g_reverser;
    g_output.ConstantSpeed = ATS_CONSTANTSPEED_CONTINUE;

    return g_output;
}

// --- 以下の関数は、プレイヤーが操作した時にBVEから呼ばれるので、値だけ記憶しておく ---
ATS_API void WINAPI SetPower(int notch) { g_powerNotch = notch; }
ATS_API void WINAPI SetBrake(int notch) { g_brakeNotch = notch; }
ATS_API void WINAPI SetReverser(int pos) { g_reverser = pos; }

// --- 今回使わない機能はすべて空っぽにする ---
ATS_API void WINAPI SetVehicleSpec(ATS_VEHICLESPEC vehicleSpec) {}
ATS_API void WINAPI Initialize(int brake) {}
ATS_API void WINAPI KeyDown(int atsKeyCode) {}
ATS_API void WINAPI KeyUp(int hornType) {}
ATS_API void WINAPI HornBlow(int atsHornBlowIndex) {}
ATS_API void WINAPI DoorOpen() {}
ATS_API void WINAPI DoorClose() {}
ATS_API void WINAPI SetSignal(int signal) {}
ATS_API void WINAPI SetBeaconData(ATS_BEACONDATA beaconData) {}