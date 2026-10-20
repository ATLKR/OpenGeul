# need to hack buildid?
if [ "${PKGFORMAT}${LIBO_VERSION_PATCH}" = "deb0" ] || \
   [ "${PKGFORMAT}${LIBO_VERSION_PATCH}" = "rpm0" ] ; then
    LIBO_VERSION_PATCH=1
fi
${PERL} -w "${SRCDIR}"/solenv/bin/make_installer.pl \
    -f "${BUILDDIR}"/instsetoo_native/util/openoffice.lst \
    -l "${LANG}" \
    -p "${PRODUCTNAME_WITHOUT_SPACES}${PRODNAME}" \
    -u "${instsetoo_OUT}" \
    -packer "${COMPRESSIONTOOL}" \
    -buildid "${LIBO_VERSION_PATCH}" \
    ${EXTRA_PARAMS:+$EXTRA_PARAMS} \
    ${EXTENSION:+"$EXTENSION"} \
    -format "${PKGFORMAT}" \
    "${VERBOSITY}"
