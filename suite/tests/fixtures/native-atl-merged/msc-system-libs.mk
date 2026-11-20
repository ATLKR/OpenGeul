define gb_MSVCRT_subst
$(if $(MSVC_USE_DEBUG_RUNTIME),$(subst msvcrt,msvcrtd,$(subst msvcprt,msvcprtd,$(subst libcmt,libcmtd,$(subst libvcruntime,libvcruntimed,$(subst libucrt,libucrtd,$(subst libcpmt,libcpmtd,$(subst msvcmrt,msvcmrtd,$(1)))))))),$(1))
endef

define gb_LinkTarget_use_system_win32_libs
$(call gb_LinkTarget_add_libs,$(1),$(foreach lib,$(2),$(call gb_MSVCRT_subst,$(lib)).lib))
$(if $(call gb_LinkTarget__is_merged,$(1)),\
	$(call gb_LinkTarget_add_libs,$(call gb_Library_get_linktarget,merged),$(foreach lib,$(2),$(call gb_MSVCRT_subst,$(lib)).lib)))
endef

