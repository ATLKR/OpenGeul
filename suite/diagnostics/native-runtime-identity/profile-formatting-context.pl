                my $section = $oneprofileitem->{'Section'};
                my $key = $oneprofileitem->{'Key'};
                my $value = $oneprofileitem->{'Value'};
                for (my $pk = 1; $pk <= 50; $pk++)
                {
                    my $key = "ValueList" . $pk;
                    if ( $oneprofileitem->{$key} )
                        { $value = $value . " " . $oneprofileitem->{$key} }
                }
                my $order = $oneprofileitem->{'Order'}; # ignoring order at the moment

                my $line = "[" . $section . "]" . "\n";
                push(@onefile, $line);
                $line = $key . "=" . $value . "\n";
                push(@onefile, $line);

                $profileempty = 0;
            }
        }

        if ( $profileempty ) { next; }  # ignoring empty profiles

        # Sorting the array @onefile
        my $onefileref = sorting_profile(\@onefile);

        if ( $installer::globals::iswin && $^O =~ /cygwin/i)      # Windows line ends only for Cygwin
        {
            include_windows_lineends($onefileref);
        }

        # Saving the profile as a file
        my $completeprofilename = $localprofilesdir . $installer::globals::separator . $profilename;

        installer::files::save_file($completeprofilename, $onefileref);
