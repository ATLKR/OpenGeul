define gb_Library_Library
$(call gb_Postprocess_register_target,AllLibraries,Library,$(1))
ifeq (,$$(filter $(1),$$(gb_Library_KNOWNLIBS)))
$$(eval $$(call gb_Output_info,Currently known libraries are: $(sort $(gb_Library_KNOWNLIBS)),ALL))
$$(eval $$(call gb_Output_error,Library $(1) must be registered in Repository.mk or RepositoryExternal.mk))
endif

$(if $(gb_Package_PRESTAGEDIR),\
    $(if $(wildcard $(gb_Package_PRESTAGEDIR)/$(call gb_Library_get_instdir,$(1))/$(call gb_Library_get_runtime_filename,$(1))),\
        $(call gb_Library__Library_impl_copy,$(0),$(call gb_Library_get_instdir,$(1))/$(call gb_Library_get_runtime_filename,$(1))),\
        $(call gb_Library__Library_impl,$(1),$(call gb_Library_get_linktarget,$(1)))\
    ),
    $(call gb_Library__Library_impl,$(1),$(call gb_Library_get_linktarget,$(1)))\
)

endef

define gb_Library__Library_impl_copy
$(call gb_Package_Package,Library_Copy_$(1),$(gb_Package_PRESTAGEDIR))
$(call gb_Package_add_file,Library_Copy_$(1),$(2),$(2))
endef

# Note: there may be targets in 3 different directories: the library itself,
# the exports target (and other misc. MSVC files) (always in
# $(WORKDIR)/LinkTarget), and the import library, which may be in SDK;
# the first 2 are always created by gb_LinkTarget_LinkTarget
# Also: the directory dependencies must be on the headers_target because
# MSVC will write a PDB file when compiling objects.
#
# call gb_Library__Library_impl,library,linktarget
define gb_Library__Library_impl
$(call gb_LinkTarget_LinkTarget,$(2),Library_$(1),$(call gb_Library_get_layer,$(1)))
$(call gb_LinkTarget_set_targettype,$(2),Library)
$(call gb_LinkTarget_add_libs,$(2),$(gb_STDLIBS))
$(call gb_LinkTarget_add_defs,$(2),\
	$(gb_Library_DEFS) \
)
$(call gb_Library_get_exports_target,$(1)) : $(call gb_Library_get_target,$(1))
$(call gb_LinkTarget_get_headers_target,$(2)) : \
	| $(dir $(call gb_Library_get_ilib_target,$(1))).dir
$(call gb_Library_get_clean_target,$(1)) : $(call gb_LinkTarget_get_clean_target,$(2))
$(call gb_Library_get_clean_target,$(1)) : AUXTARGETS :=
$(call gb_Library_Library_platform,$(1),$(2),$(call gb_Library_get_ilib_target,$(1)))

$$(eval $$(call gb_Module_register_target,$(call gb_Library_get_exports_target,$(1)),$(call gb_Library_get_clean_target,$(1))))

$(call gb_Helper_make_userfriendly_targets,$(1),Library,$(call gb_Library_get_exports_target,$(1)))

endef
gb_Library_get_runtime_filename = $(call gb_Library_get_filename,$(1))
gb_Library_get_runtime_filename_for_build = $(call gb_Library_get_filename_for_build,$(1))
