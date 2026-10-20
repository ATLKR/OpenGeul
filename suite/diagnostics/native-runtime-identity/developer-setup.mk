.PHONY: $(gb_CustomTarget_workdir)/instsetoo_native/setup/$(call gb_Helper_get_rcfile,setup)
$(gb_CustomTarget_workdir)/instsetoo_native/setup/$(call gb_Helper_get_rcfile,setup) :
	$(call gb_Output_announce,$(subst $(WORKDIR)/,,$@),$(true),ECH,1)
	$(call gb_Trace_StartRange,$(subst $(WORKDIR)/,,$@),ECH)
	( \
		echo '[Bootstrap]' \
		&& echo 'buildid=$(shell cd $(SRCDIR) && git log -1 --format=%H)' \
	) > $@
	$(call gb_Trace_EndRange,$(subst $(WORKDIR)/,,$@),ECH)
