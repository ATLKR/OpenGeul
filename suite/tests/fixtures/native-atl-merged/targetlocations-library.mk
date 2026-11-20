# linktarget = class/object<>some_optional_target, like Library/libswlo.so<>/.../instdir/program/libswlo.so
# while the target is optional, the workdir functions will always work correctly
gb_LinkTarget__get_workdir_linktargetname = $(firstword $(subst <>,  ,$(1)))
gb_LinkTarget__get_workdir_linktargetclass =  $(firstword $(subst /,  ,$(call gb_LinkTarget__get_workdir_linktargetname,$(1))))
gb_LinkTarget__get_workdir_linktargetobject = $(lastword $(subst /,  ,$(call gb_LinkTarget__get_workdir_linktargetname,$(1))))
gb_LinkTarget_get_headers_target = \
 $(WORKDIR)/Headers/$(call gb_LinkTarget__get_workdir_linktargetname,$(1))
gb_LinkTarget_get_objects_list = \
 $(WORKDIR)/LinkTarget/$(call gb_LinkTarget__get_workdir_linktargetname,$(1)).objectlist
gb_LinkTarget_get_dep_target = \
 $(WORKDIR)/Dep/LinkTarget/$(call gb_LinkTarget__get_workdir_linktargetname,$(1)).d
gb_LinkTarget_get_dep_libraries_target = \
 $(WORKDIR)/Dep/LinkTarget/$(call gb_LinkTarget__get_workdir_linktargetname,$(1)).d.libraries
gb_LinkTarget_get_dep_externals_target = \
 $(WORKDIR)/Dep/LinkTarget/$(call gb_LinkTarget__get_workdir_linktargetname,$(1)).d.externals
gb_LinkTarget_get_dep_statics_target = \
 $(WORKDIR)/Dep/LinkTarget/$(call gb_LinkTarget__get_workdir_linktargetname,$(1)).d.statics
gb_LinkTarget_get_clean_target = \
 $(WORKDIR)/Clean/LinkTarget/$(call gb_LinkTarget__get_workdir_linktargetname,$(1))
gb_LinkTarget_get_target = $(lastword $(subst <>,  ,$(1)))
define gb_Library_get_headers_target
$(patsubst $(1):%,$(WORKDIR)/Headers/Library/%,$(filter $(1):%,$(gb_Library_FILENAMES)))
endef
define gb_Library_get_filename
$(patsubst $(1):%,%,$(filter $(1):%,$(gb_Library_FILENAMES)))
endef

define gb_Library__get_workdir_linktargetname
Library/$(call gb_Library_get_filename,$(1))
endef
define gb_Library_get_target
$(call gb_Library_get_instdir,$(1))/$(call gb_Library_get_runtime_filename,$(1))
endef
ifneq ($(CROSS_COMPILING),)
define gb_Library_get_target_for_build
$(call gb_Library_get_instdir_for_build,$(1))/$(call gb_Library_get_runtime_filename_for_build,$(1))
endef
else
gb_Library_get_target_for_build = $(gb_Library_get_target)
endif # CROSS_COMPILING
# this returns a tuple of both the linktargetname, and the target file
define gb_Library_get_linktarget
$(call gb_Library__get_workdir_linktargetname,$(1))<>$(call gb_Library_get_target,$(1))
endef
gb_Library_get_linktarget_target = $(call gb_LinkTarget_get_target,$(call gb_Library_get_linktarget,$(1)))
