# call gb_LinkTarget_set_targettype,linktarget,targettype
define gb_LinkTarget_set_targettype
$(call gb_LinkTarget_get_target,$(1)) : TARGETTYPE := $(2)

endef

