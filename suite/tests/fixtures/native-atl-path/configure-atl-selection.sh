win_short_path_for_make()
{
    local short_path="$1"
    if test "$GNUMAKE_WIN_NATIVE" = "TRUE" ; then
        cygpath -sm "$short_path"
    elif test -n "$WSL_ONLY_AS_HELPER"; then
        # when already unix-style path, wslpath doesn't return anything
        case "$short_path" in
        /*)
            echo $short_path
            exit
            ;;
        esac
        wslpath -m "$(wslpath -u "$short_path")"
    else
        cygpath -u "$(cygpath -d "$short_path")"
    fi
}
if test "$build_os" = "cygwin" -o "$build_os" = wsl -o -n "$WSL_ONLY_AS_HELPER"; then
    if test -d "$COMPATH_unix/atlmfc/lib/spectre"; then
        ATL_LIB="$COMPATH/atlmfc/lib/spectre"
        ATL_INCLUDE="$COMPATH/atlmfc/include"
    elif test -d "$COMPATH_unix/atlmfc/lib"; then
        ATL_LIB="$COMPATH/atlmfc/lib"
        ATL_INCLUDE="$COMPATH/atlmfc/include"
    else
        ATL_LIB="$WINDOWS_SDK_HOME/lib" # Doesn't exist for VSE
        ATL_INCLUDE="$WINDOWS_SDK_HOME/include/atl"
    fi
    ATL_LIB="$ATL_LIB/$WIN_HOST_ARCH"
    ATL_LIB=`win_short_path_for_make "$ATL_LIB"`
    ATL_INCLUDE=`win_short_path_for_make "$ATL_INCLUDE"`
fi
