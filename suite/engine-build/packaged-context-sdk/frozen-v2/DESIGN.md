# Packaged-context read-only observer candidate

Root explicitly requested this narrow design and TDD implementation. It is scratch-only and does not change either checkout, the existing pure40 worker, a package, profile, installation or runner workflow.

## Approach

Use a small portable C++ collector core, a typed Windows SDK/C++WinRT port and an independent strict Python metadata/bundle validator. No .NET/NuGet dependency is required. A .NET helper would add restore/bootstrap uncertainty; product-private reporting or a modified MSIX would change the tested object, so neither is used. No launcher is implemented: official Invoke-CommandInDesktopPackage supports an external diagnostic process with package identity and virtualized resources, but does not document an original PROCESS_INFORMATION process HANDLE return and warns its token/other behavior need not equal the product. ActivateApplication targets the manifest application and yields a PID, not an arbitrary observer and original HANDLE. Thus original-handle/controller/watchdog authority stays unknown and every live entry rejects.

The Main manifest generator currently declares AppId OpenGeul, executable OpenGeul.exe, Windows.FullTrustApplication and runFullTrust (scripts/buildkit.py93,110). This supports selecting the documented diagnostic context; it does not prove successful WinRT activation, actual UDF equivalence or an owned launcher.

## One collector only

The core accepts caller-fixed expected package FullName/PFN/SID/native architecture, a source-only exact product identifier recipe and independently fixed product-local/product-roaming logical paths. It never chooses expected paths from its result. Current supported identifier is org.allenlabs.opengeul; both optional source recipe overrides must be null. Public source recipe digests are metadata pins, not qualified old/new MSIX proof.

The Windows port queries GetCurrentPackageFullName/FamilyName, current TokenUser, PID/creation/IsWow64Process2 and QPC, then SHGetKnownFolderPath(LocalAppData/RoamingAppData, flags0, current user) and Windows.Storage.ApplicationData.Current.LocalFolder.Path. The two requested logical product paths must independently equal those observed known-folder roots plus the exact recipe identifier. LocalState must come from WinRT, never PFN/path concatenation. It opens only existing selected directories with READ_ATTRIBUTES, share READ|WRITE|DELETE, OPEN_EXISTING, BACKUP_SEMANTICS and OPEN_REPARSE_POINT. It rejects relative/UNC/device/ADS/parent aliases and reparse components; obtains final path, volume/FileID128/creation; retains all three together; requires distinct objects; reopens/rechecks identities; rechecks self generation; closes only its own handles. No directory creation, marker, listing, profile content, WMI/browser inspection, registry modification, UI, deployment, repair or removal exists here.

The exposed share mode is the exact successful CreateFile request (7); no deletion or rename is performed to test servicing. Directory handles are short-lived observations, not a durable servicing lease. No phase packet is fabricated or auto-converted. The old pure40 requires createdByThisRun and retained servicing ownership, which this read-only observation deliberately cannot establish.

## Boundaries and evidence

Use the caller's original <=90s phase QPC window and a <=10s observer subdeadline. Portable policy checks every synchronous operation before/after it. A synchronous WinRT/OS call can overrun: no external retained-HANDLE watchdog is implemented, so bounded-live readiness remains false. No forcekill is introduced. Missing API/path, cancellation, timeout, alias, changed identity or cleanup uncertainty returns a closed failure without success payload.

ApplicationData getters are read operations in our code; Microsoft does not guarantee absence of all OS initialization side effects. Record that unknown separately; never promise physical disk immutability. Launcher token equivalence, actual browser UDF/default-root ownership, original helper HANDLE, watchdog, native compile and Windows execution remain unverified. All actualWindowsExecuted/qualification/canService/originalHelperHandleKnown/controllerOwnershipKnown/durableLease/watchdogVerified flags remain false.

## Primary references

- https://learn.microsoft.com/en-us/powershell/module/appx/invoke-commandindesktoppackage?view=windowsserver2025-ps
- https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-iapplicationactivationmanager-activateapplication
- https://learn.microsoft.com/en-us/windows/apps/develop/cpp-winrt/intro-to-using-cpp-with-winrt
- https://learn.microsoft.com/en-us/uwp/api/windows.storage.applicationdata.current
- https://learn.microsoft.com/en-us/uwp/api/windows.storage.applicationdata.localfolder
- https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandleex

Only public documentation was read. No SDK metadata/install/auth retry is involved.
