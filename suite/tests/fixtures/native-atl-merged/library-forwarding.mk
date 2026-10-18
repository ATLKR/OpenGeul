# forward the call to the gb_LinkTarget implementation
# (note: because the function name is in $(1), the other args are shifted by 1)
define gb_Library__forward_to_Linktarget
$(call gb_LinkTarget_$(subst gb_Library_,,$(1)),$(call gb_Library_get_linktarget,$(2)),$(3),$(4),Library_$(2))

endef

gb_Library_use_library_objects = $(call gb_Library__forward_to_Linktarget,$(0),$(1),$(2),$(3))
gb_Library_add_defs = $(call gb_Library__forward_to_Linktarget,$(0),$(1),$(2),$(3))
gb_Library_set_include = $(call gb_Library__forward_to_Linktarget,$(0),$(1),$(2),$(3))
gb_Library_add_ldflags = $(call gb_Library__forward_to_Linktarget,$(0),$(1),$(2),$(3))
gb_Library_add_libs = $(call gb_Library__forward_to_Linktarget,$(0),$(1),$(2),$(3))
gb_Library_use_system_win32_libs = $(call gb_Library__forward_to_Linktarget,$(0),$(1),$(2),$(3))
