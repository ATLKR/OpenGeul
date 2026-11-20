define gb_LinkTarget__is_merged
$(filter $(1),$(foreach lib,$(gb_MERGEDLIBS),$(call gb_Library_get_linktarget,$(lib))))
endef

# call gb_LinkTarget__use_linktarget_objects,linktarget,linktargets
define gb_LinkTarget__use_linktarget_objects
$(call gb_LinkTarget_get_target,$(1)) : $(foreach linktarget,$(2),$(call gb_LinkTarget_get_target,$(linktarget)))
ifneq ($(OS),iOS)
$(call gb_LinkTarget_get_target,$(1)) : EXTRAOBJECTLISTS += $(foreach linktarget,$(2),$(call gb_LinkTarget_get_objects_list,$(linktarget)))
endif

endef

# call gb_LinkTarget_use_library_objects,linktarget,libs
define gb_LinkTarget_use_library_objects
ifneq (,$$(filter-out $(gb_Library_KNOWNLIBS),$(2)))
$$(eval $$(call gb_Output_info,currently known libraries are: $(sort $(gb_Library_KNOWNLIBS)),ALL))
$$(eval $$(call gb_Output_error,Cannot import objects library/libraries $$(filter-out $(gb_Library_KNOWNLIBS),$(2)). Libraries must be registered in Repository.mk or RepositoryExternal.mk))
endif
$(call gb_LinkTarget__use_linktarget_objects,$(1),$(foreach lib,$(2),$(call gb_Library_get_linktarget,$(lib))))
$(call gb_LinkTarget_get_headers_target,$(1)) : \
	$(foreach lib,$(2),$(call gb_Library_get_headers_target,$(lib)))

endef

