# call gb_LinkTarget_add_defs,linktarget,defines
define gb_LinkTarget_add_defs
$(call gb_LinkTarget_get_target,$(1)) : DEFS += $(2)
$(call gb_LinkTarget_get_target,$(1)) : PCH_DEFS += $(2)
endef
