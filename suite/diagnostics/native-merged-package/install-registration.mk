define gb_Helper__register_libraries
$(foreach group,$(gb_Library_VALIDGROUPS),\
 $(foreach target,$(2),\
  $(if $(filter $(target),$(gb_Library_$(group))),\
   $(call gb_Output_error,gb_Helper_register_libraries: already registered: $(target)))))
$(if $(filter-out $(words $(2)),$(words $(sort $(2)))),\
 $(call gb_Output_error,gb_Helper_register_libraries: contains duplicates: $(2)))

gb_Library_$(1) += $(2)

endef
define gb_Helper_register_libraries_for_install
$(if $(3),,$(call gb_Output_error,gb_Helper_register_libraries_for_install: no libraries - need 3 parameters))
ifeq ($$(filter $(1),$$(gb_Library_VALIDGROUPS_INSTALLED)),)
$$(eval $$(call gb_Output_error,$(1) is not a valid group for installed libraries. Valid groups are: $$(gb_Library_VALIDGROUPS_INSTALLED). Use gb_Helper_register_libraries for libraries that are not installed.))
endif
$(call gb_Helper__register_libraries,$(1),$(3))

gb_Library_MODULE_$(2) += $(filter-out $(gb_MERGEDLIBS),$(3))

$(if $(filter UNOVERLIBS RTVERLIBS,$(1)),\
	gb_SdkLinkLibrary_MODULE_sdk += $(3))

endef
