# -*- Mode: makefile-gmake; tab-width: 4; indent-tabs-mode: t -*-
#
# This file is part of the LibreOffice project.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#

gb_LO_VER := $(shell . $(SRCDIR)/sources.ver && echo $$lo_sources_ver)
$(if $(gb_LO_VER),,$(error Error while retrieving $$lo_sources_ver from $(SRCDIR)/sources.ver))

get-submodules: | download
ifneq ($(foreach i,$(subst helpcontent2,help,$(GIT_NEEDED_SUBMODULES)),$(SRCDIR)/src/libreoffice-$(i)-$(gb_LO_VER)),$(wildcard $(foreach i,$(subst helpcontent2,help,$(GIT_NEEDED_SUBMODULES)),$(SRCDIR)/src/libreoffice-$(i)-$(gb_LO_VER))))
	$(foreach i,$(subst helpcontent2,help,$(GIT_NEEDED_SUBMODULES)),\
		$(call fetch_Download_item_unchecked,https://download.documentfoundation.org/libreoffice/src/$(shell echo $(gb_LO_VER) | sed -e "s/\([0-9]*\.[0-9]*\.[0-9]*\).*/\1/"),libreoffice-$(i)-$(gb_LO_VER).tar.xz))
	$(SRCDIR)/bin/unpack-sources $(SRCDIR) $(foreach i,$(subst helpcontent2,help,$(GIT_NEEDED_SUBMODULES)),\
		$(TARFILE_LOCATION)/libreoffice-$(i)-$(gb_LO_VER).tar.xz)
endif
