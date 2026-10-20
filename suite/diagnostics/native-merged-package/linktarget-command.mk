define gb_LinkTarget__command_impl
	$(if $(gb_FULLDEPS),
		$(if $(ENABLE_CUSTOMTARGET_COMPONENTS),$(if $(gb_PARTIAL_BUILD),,
			$(call gb_LinkTarget__command_dep_libraries,$(call gb_LinkTarget_get_dep_libraries_target,$(2)).tmp,$(2))
			mv $(call gb_LinkTarget_get_dep_libraries_target,$(2)).tmp $(call gb_LinkTarget_get_dep_libraries_target,$(2))
			$(call gb_LinkTarget__command_dep_externals,$(call gb_LinkTarget_get_dep_externals_target,$(2)).tmp,$(2))
			mv $(call gb_LinkTarget_get_dep_externals_target,$(2)).tmp $(call gb_LinkTarget_get_dep_externals_target,$(2))
			$(call gb_LinkTarget__command_dep_statics,$(call gb_LinkTarget_get_dep_statics_target,$(2)).tmp,$(2))
			mv $(call gb_LinkTarget_get_dep_statics_target,$(2)).tmp $(call gb_LinkTarget_get_dep_statics_target,$(2))))
		$(if $(findstring concat-deps,$(2)),,
			$(call gb_LinkTarget__command_dep,$(call gb_LinkTarget_get_dep_target,$(2)).tmp,$(2))
			mv $(call gb_LinkTarget_get_dep_target,$(2)).tmp $(call gb_LinkTarget_get_dep_target,$(2))))
	$(if $(filter $(2),$(foreach lib,$(gb_MERGEDLIBS),$(call gb_Library__get_workdir_linktargetname,$(lib)))),
		$(if $(filter $(true),$(call gb_LinkTarget__is_build_lib,$(2))),
			$(call gb_LinkTarget__command,$(1),$(2)),
			mkdir -p $(dir $(1)) && echo invalid - merged lib > $(1)
			$(if $(SOVERSIONSCRIPT),&& echo invalid - merged lib > $(WORKDIR)/LinkTarget/$(2))),
		$(if $(filter-out CompilerTest,$(TARGETTYPE)),
			$(call gb_LinkTarget__command,$(1),$(2))))
	$(call gb_LinkTarget__command_objectlist,$(WORKDIR)/LinkTarget/$(2).objectlist)
endef
define gb_LinkTarget__is_build_lib
$(if $(filter $(call gb_LinkTarget__get_workdir_linktargetname,$(1)),$(call gb_BUILD_HELPER_LIBS)),$(true))
endef
