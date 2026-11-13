# -*- Mode: makefile-gmake; tab-width: 4; indent-tabs-mode: t -*-
#
# This file is part of the LibreOffice project.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# This file incorporates work covered by the following license notice:
#
#   Licensed to the Apache Software Foundation (ASF) under one or more
#   contributor license agreements. See the NOTICE file distributed
#   with this work for additional information regarding copyright
#   ownership. The ASF licenses this file to you under the Apache
#   License, Version 2.0 (the "License"); you may not use this file
#   except in compliance with the License. You may obtain a copy of
#   the License at http://www.apache.org/licenses/LICENSE-2.0 .
#

gb_Helper_set_ld_path := $(call gb_Helper_cyg_path,PATH="$(INSTDIR_FOR_BUILD)/$(LIBO_URE_LIB_FOLDER):$(INSTDIR_FOR_BUILD)/$(LIBO_BIN_FOLDER):$$PATH")

define gb_Helper_prepend_ld_path
PATH="$(call gb_Helper_cyg_path,$(INSTDIR_FOR_BUILD)/$(LIBO_URE_LIB_FOLDER):$(INSTDIR_FOR_BUILD)/$(LIBO_BIN_FOLDER):$(1):$$PATH")
endef

# $(1): one directory pathname to append to the ld path
define gb_Helper_extend_ld_path
$(gb_Helper_set_ld_path)':$(call gb_Helper_cyg_path,$(1))'
endef
