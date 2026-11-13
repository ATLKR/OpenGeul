# call gb_LinkTarget_LinkTarget,linktarget,linktargetmakefilename,layer
define gb_LinkTarget_LinkTarget
$(call gb_LinkTarget_get_clean_target,$(1)) : LINKTARGET := $(1)
$(call gb_LinkTarget_get_clean_target,$(1)) : LINKTARGETMAKEFILENAME := $(2)
$(call gb_LinkTarget_get_clean_target,$(1)) : AUXTARGETS :=
$(call gb_LinkTarget_get_headers_target,$(1)) : SELF := $(call gb_LinkTarget__get_workdir_linktargetname,$(1))
$(call gb_LinkTarget_get_headers_target,$(1)) : \
	| $(dir $(call gb_LinkTarget_get_headers_target,$(1))).dir \
	  $(dir $(call gb_LinkTarget_get_target,$(1))).dir \
	  $(dir $(WORKDIR)/LinkTarget/$(call gb_LinkTarget__get_workdir_linktargetname,$(1))).dir
$(call gb_LinkTarget_get_target,$(1)) : ILIBTARGET :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : COBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : CXXOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : YACCOBJECT :=
$(call gb_LinkTarget_get_target,$(1)) : T_YACCFLAGS := $$(gb_LinkTarget_YYACFLAGS) $(YACCFLAGS)
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : LEXOBJECT :=
$(call gb_LinkTarget_get_target,$(1)) : T_LEXFLAGS := $$(gb_LinkTarget_LEXFLAGS) $(LEXFLAGS)
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : OBJCOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : OBJCXXOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : CXXCLROBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : ASMOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : GENCOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : GENCXXOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : GENOBJCOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : GENASMOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : GENNASMOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : GENOBJCXXOBJECTS :=
$(call gb_LinkTarget_get_clean_target,$(1)) \
$(call gb_LinkTarget_get_target,$(1)) : GENCXXCLROBJECTS :=
$(call gb_LinkTarget_get_target,$(1)) : T_CFLAGS := $$(gb_LinkTarget_CFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : T_CFLAGS_APPEND :=
$(call gb_LinkTarget_get_target,$(1)) : T_CXXFLAGS := $$(gb_LinkTarget_CXXFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : T_CXXFLAGS_APPEND :=
$(call gb_LinkTarget_get_target,$(1)) : PCH_CXXFLAGS := $$(gb_LinkTarget_CXXFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : OBJECT_HAS_EXTRA_CXXFLAGS :=
$(call gb_LinkTarget_get_target,$(1)) : T_OBJCXXFLAGS := $$(gb_LinkTarget_OBJCXXFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : T_OBJCXXFLAGS_APPEND :=
$(call gb_LinkTarget_get_target,$(1)) : T_OBJCFLAGS := $$(gb_LinkTarget_OBJCFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : T_OBJCFLAGS_APPEND :=
$(call gb_LinkTarget_get_target,$(1)) : T_NASMFLAGS := $$(NAFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : T_NASMFLAGS_APPEND :=
$(call gb_LinkTarget_get_target,$(1)) : T_CXXCLRFLAGS := $$(gb_LinkTarget_CXXCLRFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : T_CXXCLRFLAGS_APPEND :=
$(call gb_LinkTarget_get_target,$(1)) : DEFS := $$(gb_LinkTarget_DEFAULTDEFS) $(CPPFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : PCH_DEFS := $$(gb_LinkTarget_DEFAULTDEFS) $(CPPFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : INCLUDE := -I$$(SRCDIR)/include $$(gb_LinkTarget_INCLUDE)
$(call gb_LinkTarget_get_target,$(1)) : T_LDFLAGS := $$(gb_LinkTarget_LDFLAGS) $(call gb_LinkTarget_get_linksearchpath_for_layer,$(3)) $(call gb_LinkTarget__get_ldflags,$(2))
$(call gb_LinkTarget_get_target,$(1)) : LINKED_LIBS :=
$(call gb_LinkTarget_get_target,$(1)) : LINKED_STATIC_LIBS :=
$(call gb_LinkTarget_get_target,$(1)) : T_LIBS :=
$(call gb_LinkTarget_get_target,$(1)) : T_STDLIBS_CXX := $(gb_STDLIBS_CXX)
$(call gb_LinkTarget_get_target,$(1)) : TARGETTYPE :=
$(call gb_LinkTarget_get_target,$(1)) : LIBRARY_X64 :=
$(call gb_LinkTarget_get_target,$(1)) : PCH_NAME :=
$(call gb_LinkTarget_get_target,$(1)) : PCH_HEADER :=
$(call gb_LinkTarget_get_target,$(1)) : PCH_LINKTARGETMAKEFILENAME :=
$(call gb_LinkTarget_get_target,$(1)) : PCHOBJS :=
$(call gb_LinkTarget_get_target,$(1)) : PCHOBJEX :=
$(call gb_LinkTarget_get_target,$(1)) : PCHOBJNOEX :=
$(call gb_LinkTarget_get_target,$(1)) : T_PCH_EXTRA_CXXFLAGS :=
$(call gb_LinkTarget_get_target,$(1)) : PE_X86 :=
$(call gb_LinkTarget_get_target,$(1)) : PDBFILE :=
$(call gb_LinkTarget_get_target,$(1)) : TARGETGUI :=
$(call gb_LinkTarget_get_target,$(1)) : EXTRAOBJECTLISTS :=
$(call gb_LinkTarget_get_target,$(1)) : NATIVERES :=
$(call gb_LinkTarget_get_target,$(1)) : VISIBILITY :=
$(call gb_LinkTarget_get_target,$(1)) : WARNINGS_NOT_ERRORS :=
$(call gb_LinkTarget_get_target,$(1)) : WARNINGS_DISABLED :=
$(call gb_LinkTarget_get_target,$(1)) : PLUGIN_WARNINGS_AS_ERRORS :=
$(call gb_LinkTarget_get_target,$(1)) : EXTERNAL_CODE :=
$(call gb_LinkTarget_get_target,$(1)) : SOVERSIONSCRIPT :=
$(call gb_LinkTarget_get_target,$(1)) : COMPILER_TEST :=
$(call gb_LinkTarget_get_target,$(1)) : T_SYMBOLS := $(if $(call gb_target_symbols_enabled,$(2)),$(true),$(false))
$(call gb_LinkTarget_get_target,$(1)) : T_FORCE_COMPILE := $(if $(call gb_LinkTarget__force_compile,$(2)),$(true),$(false))
$(call gb_LinkTarget_get_target,$(1)) : T_CC :=
$(call gb_LinkTarget_get_target,$(1)) : T_CXX :=
$(call gb_LinkTarget_get_target,$(1)) : T_USE_LD := $(USE_LD)
$(call gb_LinkTarget_get_target,$(1)) : T_LTOFLAGS := $(gb_LTOFLAGS)
$(call gb_LinkTarget_get_target,$(1)) : T_PREJS :=

ifeq ($(gb_FULLDEPS),$(true))
ifeq (depcache:,$(filter depcache,$(.FEATURES)):$(gb_PARTIAL_BUILD))
-includedepcache $(call gb_LinkTarget_get_dep_target,$(1))
else
-include $(call gb_LinkTarget_get_dep_target,$(1))
endif
$(call gb_LinkTarget_get_dep_target,$(1)) : COBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : CXXOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : OBJCOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : OBJCXXOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : CXXCLROBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : ASMOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : GENCOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : GENCXXOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : GENOBJCOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : GENOBJCXXOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : GENASMOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : GENNASMOBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : GENCXXCLROBJECTS :=
$(call gb_LinkTarget_get_dep_target,$(1)) : YACCOBJECTS :=
endif # gb_FULLDEPS

gb_LinkTarget_CXX_SUFFIX_$(call gb_LinkTarget__get_workdir_linktargetname,$(1)) := cxx

# installed linktargets need a rule to build!
$(if $(findstring $(INSTDIR),$(1)),$(call gb_LinkTarget__make_installed_rule,$(1)))

$(call gb_PrecompiledHeader_generate_timestamp_rule,$(2))

endef # gb_LinkTarget_LinkTarget

