sub sorting_profile {
    my ($profilesref) = @_;

    my @sections;
    my %section_content;

    for ( my $i = 0; $i < @{$profilesref}; $i++ ) {
        my $line = ${$profilesref}[$i];

        # Skip unless this is a section (every second line)
        next unless ( $line =~ /^\s*(\[.*\])\s*$/ );

        my $section = $1;
        my $next_line = ${$profilesref}[$i+1];

        if ( ! exists $section_content{$section} ) {
            push @sections, $section;
        }

        push @{ $section_content{$section} }, $next_line;
    }

    my @profile;

    for my $section (@sections) {
        push @profile, "$section\n";
        push @profile, @{ $section_content{$section} };
    }

    return \@profile;
}
