# ARM64 9dea Writer server observer backend

이 폴더는 별도로 표시하는 Writer 진단 backend다. Portable 검사와 실제 Windows 빌드·실행 결과는 구분한다. normal qualification·acceptance·GUI 검증은 모두 false다. 원 get_accFocus 결과나 focus를 고치는 기능은 없다.

`wire.h`, `wire-schema.json`, `descriptor.h`가 frontend 계약이다. IPC1은 private Identity128+Control128+숫자 Row64×2048, 총131328 bytes다. descriptor는 controller PID/birth·nonce·mapping 크기/namespace만 가진다. 원 runtime S/D/frequency/owner는 arm된 immutable header에서만 확인한다. `private_sink.hxx`는 같은 process의 두 DLL에만 쓰는 ABI2 80/32 callback이다. 이 pointer 포함 인자는 IPC/JSON이 아니다.

`recorder.h`는 root Unbound→Claimed→Ready/Invalid, bounded CAS reservation·commit-last·전체 hole scan과 bounded TLS stack을 구현한다. 모든 새 mark는 같은 Root Ready·Armed·cutoff를 재확인한다. 열린 gate의 Enter CAS32회 경합 소진도 dropped/incomplete로 남겨 정상 무관측과 구별한다. 원 source QPC가 bind보다 앞서면 나중에 callback이 도착해도 거절한다. scope/thread/parent ordinal은2048 이하의 module private counter이며 raw TID/pointer가 아니다. Leave는 Closed·expired·Invalid와 독립적으로 token 정리를 시도한다. active release도 최대32 CAS이며 실패하면 active를0으로 만들지 않고 incomplete/cleanupErrors를 남긴다.

`native.cpp` 한 translation unit이 session·recorder·root와 native context를 소유한다. Setup 유일 승자는 실제 sink 코드 주소 FROM_ADDRESS|PIN, descriptor·mapping·원 HWND/PID/TID/birth·controller HANDLE/birth·QPC를 검증한다. pre-arm/실패는 resident Failed이며 경쟁자 대기·재시도는 없다. Enter만 captured controller HANDLE의 timeout0 liveness를 확인한다. Mark/invalidation은 atomic·immutable facts만 다룬다. source 경계의 QPC sample은 별도다. Setup Win32/loader 작업은 동기·잠재 blocking이며 deadline으로 강제 선점되지 않는다. PIN은 영구 module 수명 변경이다.

source.patch는 MAccessible.cxx, effective manager.cxx, manager header, 두 Library를 함께 변경한다. manager baseline은 core9dea 정상 source producer의 winAccFocusOrder 적용 뒤인5e5f42a6b448c0d9c70a05bf762e86951565b5a96decaf050399f577dd38332b다. 이미 수정된 old-focus unset→new-focus set 순서를 유지한다. root bind는 원 AddRef 아래 기존 map lock 안이다. 원 getter SolarMutex·VT store·HRESULT, 원 PutFocus assignment/parent call 순서를 유지한다. DeleteFromHwndXAcc는 기존 found 조건 안에 observer와 erase를 함께 둔다.

installer 사용은 `python install.py --source-root <fresh effective Core tree> --target windows-arm64 --core-commit 9dea406ab7695df6325b11b0e19fdca8db4b7276`이다. source/payload/schema/patch를 전부 검증한 뒤 쓴다. stdout source receipt는 ipcVersion1/sinkAbiVersion2/mappingBytes131328/descriptorSchemaVersion1/wireSchema digest와 requiredRebuiltLibraries 두 개를 담는다. 이 lock으로 UAccCOM과 winaccessibility를 모두 rebuild해야 한다. 한 DLL overlay나 ABI가 다른 pair는 금지다. producer·marker·normal consumer 조기거절·frontend controller·CI는 별도 담당 범위이며 여기서 구현했다고 주장하지 않는다.

첫 callback 설치 전 bootstrap 수명은 normal service import에 의존한다. Library_winaccessibility의 use_libraries(UAccCOM), AccObject의 UAccCOMCreateInstance 직접호출, accHelper.hxx와 UAccCOMdllapi.h의 SAL_DLLPUBLIC_IMPORT가 source 근거다. 모든 COM ref가0이어도 live service import와 독립적으로 DLL이 사라진다고 가정하지 않는다. service가 살아 있는 bootstrap과 Setup PIN 뒤 process lifetime은 다른 계약이다. 실제 Windows PE import table은 아직 확인하지 않았다. PIN API 실패 뒤 module reload를 아우르는 process 전체 native attempt 유일성도 주장하지 않는다.

pre-arm, 첫 Setup Ready/Root Bind 이전, 초기 등록, 특정 client invocation 귀속, 독립 HWND birth는 Unknown이다. wholeOriginalIntervalCovered=false다. local unmap/active0/PIN은 remote retirement 근거가 아니다. 원 retained engine HANDLE의 D 이내 실제 exit만 controller가 remote retirement로 승격할 수 있다.

재현은 repository root에서 다음 한 명령이다.

```sh
python3 -B -m unittest discover -s suite/tests -p 'test_writer_server_backend.py'
```

Portable unittest가 wire/descriptor,15 recorder 계약,16-thread Setup 경쟁, 실제 locked installer/source method/header/route/map deletion,5 native boundary mode, 강제 active-release·admission 경합을 검사한다. compiler가 없으면 C++ 부분만 명시적으로 Skip하며 Python source-lock/tamper/hardlink 검사는 계속 실행한다. compile30초/run5~15초로 제한하고 Windows `.exe` 및 기존 completed-image cleanup을 재사용한다. 실제 설치된 원본·관측판을 C++ fixture로 컴파일해 getter6분기, PutFocus3인자×parent exception 유무, focus old/new 순서, route15조건, map found/missing을 비교한다. native.cpp의 Win32 함수는 설치 SDK가 없는 Linux에서 특정 경계 fake로 대체했다. 이는 실제 Win32 ABI·PE import·ARM64 atomic/TLS·two-DLL link·GUI/RPC·30초 실제 cleanup 증거가 아니다. 과거 bf6 TDD.json은 이 lane의 검증으로 복사하지 않는다. 새 source9dea Windows 빌드·실행은 별도 검증해야 한다. tests/upstream의 byte-identical source fixture와 bf6 PCH rule oracle은 portable 검사 자료이며 새 Windows 검증이 아니다.

이 lane은 ARM64 전용 core9dea 정상 producer254에서 normal recipe9b105의 arm64Full→winAccFocusOrder 영수증 검증 직후 observer를 덧씌운다. 정상 recipe와 source policy는 변경하지 않는다. Source13 입력과 두 DLL 진단 산출물은 normal qualification·고객 배포 대상이 아니다. 기존 bf6 observer 브랜치와 그 증거는 역사 자료로 보존한다.
