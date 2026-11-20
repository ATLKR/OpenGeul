define gb_CObject__command_pattern
$(call gb_Helper_abbreviate_dirs,\
	mkdir -p $(dir $(1)) $(dir $(4)) && \
	unset INCLUDE && \
	$(if $(and $(gb_COMPILERDEPFLAGS),$(T_USE_CLANG)), export SHOWINCLUDES_PREFIX="${LO_CLANG_SHOWINCLUDES_PREFIX}" &&) \
	$(gb_COMPILER_SETUP) \
	$(call gb_CObject__compiler,$(2),$(3),$(6)) \
		$(call gb_Helper_remove_overridden_flags, \
			$(DEFS) \
			$(if $(filter YES,$(LIBRARY_X64)), ,$(gb_LTOFLAGS)) \
			$(if $(6), $(call gb_CObject__filter_out_clang_cflags,$(2)),$(2)) \
			$(if $(WARNINGS_DISABLED),$(gb_CXXFLAGS_DISABLE_WARNINGS)) \
			$(if $(EXTERNAL_CODE), \
				$(if $(filter -clr,$(2)),,$(if $(COM_IS_CLANG),-Wno-undef)), \
				$(gb_DEFS_INTERNAL)) \
			$(if $(WARNINGS_NOT_ERRORS),$(if $(ENABLE_WERROR),$(if $(PLUGIN_WARNINGS_AS_ERRORS),$(gb_COMPILER_PLUGINS_WARNINGS_AS_ERRORS))),$(gb_CFLAGS_WERROR)) \
			$(if $(filter -clr,$(2)),,$(if $(5),$(gb_COMPILER_PLUGINS))) \
			$(if $(COMPILER_TEST),-fsyntax-only -ferror-limit=0 -Xclang -verify) \
			$(PCHFLAGS) \
			$(if $(COMPILER_TEST),,$(gb_COMPILERDEPFLAGS)) \
			$(if $(filter YES,$(LIBRARY_X64)), -U_X86_ -D_AMD64_,) \
			$(if $(filter YES,$(PE_X86)), -D_X86_ -U_AMD64_,)) \
		$(INCLUDE) \
		-Fd$(PDBFILE) \
		-c $(3) \
		-Fo$(1)) \
		$(if $(COMPILER_TEST),,$(call gb_create_deps,$(4),$(1),$(3)))
endef
