# Proposal fixture generator. Only `make -n fixture` is permitted for generation.
# Exact upstream macros write csproj via $(file); no dotnet command is executed by -n.
# SNAPSHOT, FIXTURE_SOURCE and WORKDIR must be caller-owned validated absolute paths.
.DEFAULT_GOAL := fixture
gb_DotnetLibrary_workdir := $(WORKDIR)/DotnetLibrary
gb_CustomTarget_workdir := $(WORKDIR)/CustomTarget
SRCDIR := $(FIXTURE_SOURCE)
DOTNET := dotnet
ENABLE_DEBUG :=
gb_DotnetLibrary_get_target = $(gb_DotnetLibrary_workdir)/$(1)/$(1).dll
gb_DotnetLibrary_get_clean_target = $(gb_DotnetLibrary_workdir)/$(1)/clean
gb_CustomTarget_get_target = $(gb_CustomTarget_workdir)/$(1)/done
gb_Helper_abbreviate_dirs = $(1)
gb_Helper_print_on_error = $(1)
gb_Helper_make_userfriendly_targets =
gb_Module_register_target =
gb_Output_announce =
gb_Trace_StartRange =
gb_Trace_EndRange =
include $(SNAPSHOT)/solenv/gbuild/DotnetLibrary.mk
include $(SNAPSHOT)/net_ure/DotnetLibrary_net_basetypes.mk
include $(SNAPSHOT)/net_ure/DotnetLibrary_net_uretypes.mk
include $(SNAPSHOT)/net_ure/DotnetLibrary_net_oootypes.mk
include $(SNAPSHOT)/net_ure/DotnetLibrary_net_bridge.mk
$(call gb_CustomTarget_get_target,net_ure/net_uretypes) $(call gb_CustomTarget_get_target,net_ure/net_oootypes):
	@true
.PHONY: fixture
fixture: $(foreach p,net_basetypes net_uretypes net_oootypes net_bridge,$(call gb_DotnetLibrary_get_target,$(p)))
