# Here we include the file (in it there will be a call to gb_Module_register_target)
define gb_Module__read_targetfile
gb_Module_CURRENTTARGET :=
gb_Module_CURRENTCLEANTARGET :=
gb_Module_CURRENTMAKEFILE := $(patsubst $(1):%,%,$(filter $(1):%,$(gb_Module_MODULELOCATIONS)))$(2).mk
include $(patsubst $(1):%,%,$(filter $(1):%,$(gb_Module_MODULELOCATIONS)))$(2).mk
gb_Module_CURRENTMAKEFILE :=
ifneq ($$(words $$(gb_Module_CURRENTTARGET)) $$(words $$(gb_Module_CURRENTCLEANTARGET)),1 1)
$$(eval $$(call gb_Output_error,No $(3) registered while reading $(patsubst $(1):%,%,$(filter $(1):%,$(gb_Module_MODULELOCATIONS)))$(2).mk!))
endif

endef

define gb_Module_add_target
$(if $(filter AllLang% Dictionary% Package_registry,$(2)),$(warning target $(2) should be a l10n target))
$(call gb_Module__read_targetfile,$(1),$(2),target)

$(call gb_Module_get_nonl10n_target,$(1)) : $$(gb_Module_CURRENTTARGET)
$(call gb_Module_get_clean_target,$(1)) : $$(gb_Module_CURRENTCLEANTARGET)

endef
define gb_Module__modulefile
$(patsubst $(1):%,%,$(filter $(1):%,$(gb_Module_MODULELOCATIONS)))/$(2)/Module_$(2).mk
endef

define gb_Module_add_moduledir
$(if $(wildcard $(call gb_Module__modulefile,$(1),$(2))),,$(call gb_Output_error,Module does not exist: $(call gb_Module__modulefile,$(1),$(2))))
include $(call gb_Module__modulefile,$(1),$(2))
$(call gb_Module_get_target,$(1)) : $$(firstword $$(gb_Module_TARGETSTACK))
$(call gb_Module_get_l10n_target,$(1)) : $$(firstword $$(gb_Module_L10NTARGETSTACK))
$(call gb_Module_get_check_target,$(1)) : $$(firstword $$(gb_Module_CHECKTARGETSTACK))
$(call gb_Module_get_slowcheck_target,$(1)) : $$(firstword $$(gb_Module_SLOWCHECKTARGETSTACK))
$(call gb_Module_get_screenshot_target,$(1)) : $$(firstword $$(gb_Module_SCREENSHOTTARGETSTACK))
$(call gb_Module_get_coverage_target,$(1)) : $$(firstword $$(gb_Module_COVERAGETARGETSTACK))
$(call gb_Module_get_subsequentcheck_target,$(1)) : $$(firstword $$(gb_Module_SUBSEQUENTCHECKTARGETSTACK))
$(call gb_Module_get_perfcheck_target,$(1)) : $$(firstword $$(gb_Module_PERFCHECKTARGETSTACK))
$(call gb_Module_get_uicheck_target,$(1)) : $$(firstword $$(gb_Module_UICHECKTARGETSTACK))
$(call gb_Module_get_clean_target,$(1)) : $$(firstword $$(gb_Module_CLEANTARGETSTACK))
gb_Module_TARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_TARGETSTACK)),$$(gb_Module_TARGETSTACK))
gb_Module_L10NTARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_L10NTARGETSTACK)),$$(gb_Module_L10NTARGETSTACK))
gb_Module_CHECKTARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_CHECKTARGETSTACK)),$$(gb_Module_CHECKTARGETSTACK))
gb_Module_SLOWCHECKTARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_SLOWCHECKTARGETSTACK)),$$(gb_Module_SLOWCHECKTARGETSTACK))
gb_Module_SCREENSHOTTARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_SCREENSHOTTARGETSTACK)),$$(gb_Module_SCREENSHOTTARGETSTACK))
gb_Module_COVERAGETARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_COVERAGETARGETSTACK)),$$(gb_Module_COVERAGETARGETSTACK))
gb_Module_SUBSEQUENTCHECKTARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_SUBSEQUENTCHECKTARGETSTACK)),$$(gb_Module_SUBSEQUENTCHECKTARGETSTACK))
gb_Module_PERFCHECKTARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_PERFCHECKTARGETSTACK)),$$(gb_Module_PERFCHECKTARGETSTACK))
gb_Module_UICHECKTARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_UICHECKTARGETSTACK)),$$(gb_Module_UICHECKTARGETSTACK))
gb_Module_CLEANTARGETSTACK := $$(wordlist 2,$$(words $$(gb_Module_CLEANTARGETSTACK)),$$(gb_Module_CLEANTARGETSTACK))

endef

define gb_Module_add_targets
$(call gb_Module_get_target,$(1)) : $(call gb_Module_get_nonl10n_target,$(1))
$(foreach target,$(2),$(call gb_Module_add_target,$(1),$(target)))

endef
define gb_Module_add_moduledirs
$(foreach target,$(sort $(2)),$(call gb_Module_add_moduledir,$(1),$(target)))

endef
