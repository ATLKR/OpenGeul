# call gb_LinkTarget_set_include,linktarget,includes
define gb_LinkTarget_set_include
$(call gb_LinkTarget__check_srcdir_paths,$(1),\
    $(patsubst -I%,%,$(filter -I$(SRCDIR)/%,$(filter-out -I$(INSTDIR)/% -I$(WORKDIR)/%,$(2)))))
$(call gb_LinkTarget_get_target,$(1)) : INCLUDE := $(2)

endef

# call gb_LinkTarget_add_ldflags,linktarget,ldflags
define gb_LinkTarget_add_ldflags
$(call gb_LinkTarget_get_target,$(1)) : T_LDFLAGS += $(2)

endef

# real use in RepositoryExternal.mk
# call gb_LinkTarget_set_ldflags,linktarget,ldflags
define gb_LinkTarget_set_ldflags
$(call gb_LinkTarget_get_target,$(1)) : T_LDFLAGS := $(2)

endef

# call gb_LinkTarget_add_libs,linktarget,libs
define gb_LinkTarget_add_libs
$(call gb_LinkTarget_get_target,$(1)) : T_LIBS += $(2)
$(if $(call gb_LinkTarget__is_merged,$(1)),\
  $(call gb_Library_get_linktarget_target,merged) : T_LIBS += $(2))
ifeq ($(ENABLE_CUSTOMTARGET_COMPONENTS),TRUE)
$(if $(gb_DEBUG_STATIC),$$(info $$(call gb_LinkTarget__get_all_libraries_var,$(1)) += $(filter-out $(call gb_LinkTarget__get_all_libraries,$(1)),$(patsubst %,$(gb_LinkTarget__syslib),$(2)))))
$$(eval $$(call gb_LinkTarget__get_all_libraries_var,$(1)) += $(filter-out $(call gb_LinkTarget__get_all_libraries,$(1)),$(patsubst %,$(gb_LinkTarget__syslib),$(2))))
ifeq (,$(gb_PARTIAL_BUILD))
$(call gb_LinkTarget_get_target,$(1)) : LINKED_LIBS += $(filter-out $(call gb_LinkTarget__get_all_libraries,$(1)),$(patsubst %,$(gb_LinkTarget__syslib),$(2)))
endif
endif

endef
