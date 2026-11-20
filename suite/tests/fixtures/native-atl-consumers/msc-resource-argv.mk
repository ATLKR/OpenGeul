define gb_WinResTarget__command
$(call gb_Output_announce,$(2),$(true),RC ,1)
$(call gb_Helper_abbreviate_dirs,\
	mkdir -p $(dir $(1)) && \
	$(gb_RC) \
		$(DEFS) $(FLAGS) \
		$(INCLUDE) \
		-Fo$(1) \
		$(RCFILE) )
endef

$(eval $(call gb_Helper_make_dep_targets,\
	WinResTarget \
))

ifeq ($(gb_FULLDEPS),$(true))
gb_WinResTarget__command_target := $(gb_Executable_BINDIR_FOR_BUILD)/makedepend.exe
define gb_WinResTarget__command_dep
$(call gb_Output_announce,RC:$(2),$(true),DEP,1)
	$(call gb_Trace_StartRange,RC:$(2),DEP)
$(call gb_Helper_abbreviate_dirs,\
	mkdir -p $(dir $(1)) && \
	$(call gb_Executable_get_target_for_build,makedepend) \
		$(INCLUDE) \
		$(DEFS) \
		$(RCFILE) \
		-o .res \
		-p $(dir $(3)) \
		-f $(1))
	$(call gb_Trace_EndRange,RC:$(2),DEP)
endef
else
gb_WinResTarget__command_target =
gb_WinResTarget__command_dep =
endif
