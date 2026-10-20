sub replace_setup_variables
{
    my ($itemsarrayref, $languagestringref, $hashref) = @_;

    my $languagesstring = $$languagestringref;
    $languagesstring =~ s/\_/ /g;   # replacing underscore with whitespace

    my $productname = $hashref->{'PRODUCTNAME'};
    my $productversion = $hashref->{'PRODUCTVERSION'};
    my $libo_version_major = "";
    if ( $hashref->{'LIBO_VERSION_MAJOR'} ) { $libo_version_major = $hashref->{'LIBO_VERSION_MAJOR'}; }
    my $productkey = $productname . " " . $productversion;

    # string $buildid, which is used to replace the setup variable <buildid>

    my $localbuild = $installer::globals::build;

    if ( $localbuild =~ /^\s*(\w+?)(\d+)\s*$/ ) { $localbuild = $2; }   # using "680" instead of "src680"

    my $buildidstring = `git -C $ENV{'SRCDIR'} log -n 1 --pretty=format:"%H"`;
    if ($? || !$buildidstring) {
        $buildidstring = $localbuild . "(Build:" . $installer::globals::buildid . ")";
    }

    my $updateid = $productname . "_" . $libo_version_major . "_" . $$languagestringref;
    $updateid =~ s/ /_/g;

    my $updatechannel = 'LOOnlineUpdater';

    for ( my $i = 0; $i <= $#{$itemsarrayref}; $i++ )
    {
        my $oneitem = ${$itemsarrayref}[$i];
        my $value = $oneitem->{'Value'};

        $value =~ s/\<buildid\>/$buildidstring/;
        $value =~ s/\<sequence_languages\>/$languagesstring/;
        $value =~ s/\<productkey\>/$productkey/;
        $value =~ s/\<alllanguages\>/$languagesstring/;
        $value =~ s/\<sourceid\>/$installer::globals::build/;
        $value =~ s/\<updateid\>/$updateid/;
        $value =~ s/\<updatechannel\>/$updatechannel/;
        $value =~ s/\<pkgformat\>/$installer::globals::packageformat/;
        $ENV{'OOO_VENDOR'} = "" if !defined $ENV{'OOO_VENDOR'};
        $value =~ s/\<vendor\>/$ENV{'OOO_VENDOR'}/;

        $oneitem->{'Value'} = $value;
    }
}
