define instsetoo_native_genversionini
[Version]
AllLanguages=$(if $(gb_WITH_LANG),$(gb_WITH_LANG),en-US)
buildid=$(shell cd $(SRCDIR) && git log -1 --format=%H)
ExtensionUpdateURL=https://updateexte.libreoffice.org/ExtensionUpdateService/check.Update
UpdateChannel=$(if $(ENABLE_ONLINE_UPDATE_MAR),LOOnlineUpdater)
ReferenceOOoMajorMinor=4.1
UpdateID=$(PRODUCTNAME)_$(LIBO_VERSION_MAJOR)_en-US
UpdateURL=$(if $(ENABLE_ONLINE_UPDATE),https://update.libreoffice.org/check.php$(if $(filter-out WNT,$(OS)),?pkgfmt=$(PKGFORMAT)))
UpdateUserAgent=<PRODUCT> ($${buildid}; $${_OS}; $${_ARCH}; <OPTIONAL_OS_HW_DATA>)
Vendor=$(OOO_VENDOR)
endef



.PHONY: $(gb_CustomTarget_workdir)/instsetoo_native/setup/$(call gb_Helper_get_rcfile,version)
$(gb_CustomTarget_workdir)/instsetoo_native/setup/$(call gb_Helper_get_rcfile,version) :
	$(call gb_Output_announce,$(subst $(WORKDIR)/,,$@),$(true),ECH,1)
	$(call gb_Trace_StartRange,$(subst $(WORKDIR)/,,$@),ECH)
	$(file > $@,$(call instsetoo_native_genversionini))
	$(call gb_Trace_EndRange,$(subst $(WORKDIR)/,,$@),ECH)
