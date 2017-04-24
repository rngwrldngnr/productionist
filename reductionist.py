import re  # Used to parse definitions of rule bodies
import argparse  # Used to handle command-line arguments for this program
import json  # Used to generate JSON grammar files in the Productionist format
import operator  # Used to determine total number of generable lines of dialogue for a symbol/rule/grammar
import itertools  # Used to efficiently compute combinatorics when deriving grammar paths
import marisa_trie  # Used to build a trie data structure efficiently storing all the paths through the grammar


class Reductionist(object):
    """A system that, at authoring time, processes and indexes an Expressionist grammar."""

    def __init__(self, path_to_input_content_file, path_to_write_output_files_to, verbosity=1):
        """Initialize a Reductionist object."""
        # If verbosity is 0, no information will be printed out during processing; if 1, information
        # about how far along Reductionist is in its general processing will be printed out; if 2,
        # information about the paths taken through the grammar to generate content will also be printed
        self.verbosity = verbosity
        # Build a grammar in memory, as an object of the Grammar class, by parsing a JSON file
        # exported by Expressionist
        self.grammar = Grammar(
            grammar_file_location=path_to_input_content_file
        )
        # Create a start symbol and set of top-level production rules in the grammar
        self.grammar.create_start_symbol_and_top_level_production_rules()
        # Sort the symbol and rule lists
        self.grammar.nonterminal_symbols.sort(key=lambda s: s.id)
        self.grammar.production_rules.sort(key=lambda r: r.id)
        # Perform validation checks on the grammar; if these critically fail, there's no point in going forward,
        # in which case we'll short-circuit here and print out the errors
        self.validator = Validator(grammar=self.grammar)
        if not self.validator.errors:
            # Determine the grammar's total number of generable outputs
            self.total_generable_outputs = self.grammar.start_symbol.count_generable_variants()
            # Operate over the grammar to build a trie data structure that efficiently stores all the
            # semantically meaningful paths through the grammar (i.e., ones that pass through nonterminal
            # symbols with tags)
            self.trie = self._build_trie()
            # Save this trie to a file using the marisa_trie package; this file will be loaded at runtime
            # for use by Productionist
            self._save_trie(trie_file_location='{path}.marisa'.format(path=path_to_write_output_files_to))
            # Construct the set of expressible meanings for this grammar -- these pertain to each of the
            # possible tagsets that generated content may come packaged with, and each expressible meaning
            # bundles its associated tagset with recipes for producing that content (in the form of paths
            # through the grammar)
            self.expressible_meanings = self._construct_expressible_meanings()
            # Save this set of expressible meanings to a file (using my invented '.meanings' file
            # extension); this file will be loaded at runtime for use by Productionist
            self._save_expressible_meanings(
                expressible_meanings_file_location='{path}.meanings'.format(path=path_to_write_output_files_to)
            )
            # Finally, save a content file that will allow Productionist to execute recipes (grammar paths)
            # associated with expressible meanings
            self._save_grammar(
                grammar_file_location='{path}.grammar'.format(path=path_to_write_output_files_to)
            )
            # Write a stats file
            self._write_stats_file(
                stats_file_location='{path}.stats'.format(path=path_to_write_output_files_to)
            )

    def _build_trie(self):
        """Operate over the associated grammar to build a trie containing all its semantically meaningful paths.

        This method first prunes the space of possible paths through the grammar by marking which
        production rules are not semantically meaningful. A rule is marked as semantically meaningful
        if any of the symbols in its rule body have tags, or, by a recursive reasoning, if it has any
        descendant rules that are semantically meaningful. (The descendant rules of a given rule are
        the rules associated with the symbols in its body, and the rules associated with the symbols in
        the bodies of *those* rules, and so forth recursively.) Intuitively, if a rule is determined
        to not be semantically meaningful, that means that anything below it in the grammar only generates
        lexical/syntactic variation, not variation in terms of the tags that will be attached to content.

        Having pruned the space of possible paths in this way, we can now say that
        """
        if self.verbosity > 0:
            print "Indexing grammar..."
        # First, determine which production rules are semantically meaningful; this is a trick we
        # utilize during trie building that critically lets us prune the space of possible paths
        # through the grammar by only representing the semantically important parts of grammar paths
        # (i.e., the parts that flow through nonterminal symbols with tags)
        for rule in self.grammar.production_rules:
            self._determine_if_production_rule_is_semantically_meaningful(production_rule=rule)
        for symbol in self.grammar.nonterminal_symbols:
            self._determine_if_nonterminal_symbol_is_semantically_meaningful(nonterminal_symbol=symbol)
        # First, compile the set of semantically meaningful paths through the grammar; the result
        # will be a list of unique paths, each represented as a string representing the sequence
        # of production rules, in order, that must be executed to produce a given generable line
        # of content (which will come with the set of tags attached to the named rules in the path
        # string); rules are named by their IDs; e.g., a path string might look like this:
        # u'11,9,*,*,*,2,7,*,121', where the rules with IDs 11, 9, 2, 7, and 121 are named, while four
        # other rules that are not semantically meaningful are only referenced using wildcards ('*')
        all_semantically_meaningful_paths = self._collect_grammar_paths_descending_from_nonterminal_symbol(
            nonterminal_symbol=self.grammar.start_symbol
        )
        # To save on memory, exploit the amount of overlap between the nodes in these paths by
        # building a trie that efficiently stores all the path strings
        if self.verbosity > 0:
            print "Building a trie..."
        trie = marisa_trie.Trie(all_semantically_meaningful_paths)
        return trie

    def _determine_if_production_rule_is_semantically_meaningful(self, production_rule):
        """Return whether the given production rule is semantically meaningful.

        A production rule is semantically meaningful if it has tags, or if any production rule that descends
        from it has tags.
        """
        if production_rule.semantically_meaningful is not None:
            return production_rule.semantically_meaningful
        if production_rule.tags:
            production_rule.semantically_meaningful = True
        else:
            all_direct_descendant_rules = []
            for symbol in production_rule.body:
                if type(symbol) != unicode:
                    all_direct_descendant_rules += symbol.production_rules
            production_rule.semantically_meaningful = any(
                self._determine_if_production_rule_is_semantically_meaningful(production_rule=rule)
                for rule in all_direct_descendant_rules
            )
        return production_rule.semantically_meaningful

    @staticmethod
    def _determine_if_nonterminal_symbol_is_semantically_meaningful(nonterminal_symbol):
        """Return whether the given nonterminal_symbol rule is semantically meaningful.

        A production rule is semantically meaningful if it has tags, or if any production rule that descends
        from it has tags.
        """
        if nonterminal_symbol.semantically_meaningful is not None:
            return nonterminal_symbol.semantically_meaningful
        if nonterminal_symbol.tags or any(r for r in nonterminal_symbol.production_rules if r.semantically_meaningful):
            nonterminal_symbol.semantically_meaningful = True
        else:
            nonterminal_symbol.semantically_meaningful = False
        return nonterminal_symbol.semantically_meaningful

    def _collect_grammar_paths_descending_from_nonterminal_symbol(self, nonterminal_symbol, n_tabs_for_debug=0):
        """Return all grammar paths that descend from the given nonterminal symbol."""
        if self.verbosity > 1:
            print "{whitespace}Collecting grammar paths descending from symbol [[{symbol_name}]]".format(
                whitespace=n_tabs_for_debug * '  ', symbol_name=nonterminal_symbol.name
            )
        grammar_paths = set()
        for rule in nonterminal_symbol.production_rules:
            grammar_paths |= self._collect_grammar_paths_descending_from_production_rule(
                production_rule=rule, n_tabs_for_debug=n_tabs_for_debug + 1
            )
        return grammar_paths

    def _collect_grammar_paths_descending_from_production_rule(self, production_rule, n_tabs_for_debug):
        """Return all grammar paths that descend from the given production rule."""
        if self.verbosity > 1:
            print "{whitespace}Collecting grammar paths descending from rule #{rule_id}".format(
                whitespace=n_tabs_for_debug * '  ', rule_id=production_rule.id
            )
        if production_rule.semantically_meaningful:
            cartesian_product_of_all_symbols_in_this_rule_body = set(itertools.product(
                *[self._collect_grammar_paths_descending_from_nonterminal_symbol(
                    nonterminal_symbol=symbol, n_tabs_for_debug=n_tabs_for_debug + 1
                )
                  for symbol in production_rule.body if type(symbol) is not unicode and symbol.semantically_meaningful]
                # If type(symbol) == unicode, then that's a terminal symbol (i.e., it's just a string)
            ))
            if cartesian_product_of_all_symbols_in_this_rule_body:
                # Now prepend these partial rule chains with the ID for this rule (if it is semantically
                # meaningful, otherwise a wildcard, denoted by '*') and then return this
                # string as a partial rule chain
                partial_rule_chains = set()
                for rule_combination in cartesian_product_of_all_symbols_in_this_rule_body:
                    rule_combination = [combo for combo in rule_combination if combo]
                    if any(rule_combination):
                        partial_rule_chain = u"{my_id}{partial_chain}".format(
                            my_id='{},'.format(production_rule.id) if production_rule.semantically_meaningful else '',
                            partial_chain=','.join(rule_combination)
                        )
                        partial_rule_chains.add(partial_rule_chain)
                partial_rule_chains = partial_rule_chains if partial_rule_chains else {unicode(production_rule.id)}
            elif production_rule.semantically_meaningful:
                # This production rule is semantically meaningful, but nothing below it is; we
                # can simply return a list containing only the ID of this rule
                partial_rule_chains = {u"{}".format(production_rule.id)}
            else:
                partial_rule_chains = {u''}
        else:
            # This is a terminal rule, which means we don't need to keep track of it in any rule chain
            # that it is a part of (since we only want to keep track of rules that have symbols in their
            # body that are semantically meaningful -- i.e., that have tags -- or that have descendants
            # that are semantically meaningful; because we don't really care about this symbol, we'll
            # just represent it in a rule chain using a wildcard symbol; later on, this will allow us
            # to determine which rule chains are semantically equivalent, since we can just throw out
            # the wildcard symbols and match the IDs of semantically meaningful rules
            partial_rule_chains = {u''}
        return partial_rule_chains

    def _save_trie(self, trie_file_location):
        """Save a built trie to a file."""
        if self.verbosity > 0:
            print "Saving trie..."
            self.trie.save(trie_file_location)

    def _construct_expressible_meanings(self):
        """Construct a set of expressible meanings that may be used to drive content generation.

        An expressible meaning, modeled using the class defined below, corresponds to a unique
        set of tags that may be associated with generable content, bundled together with a set of
        paths through the grammar that may be taken to generate content with those tags. In other words,
        a given expressible meaning couples a specific generable meaning with a set of recipes
        for producing content that expresses that meaning.

        This method works by iterating over the semantically meaningful grammar paths contained in
        the trie, collecting all the tags attached to each named rule in that path, and then adding
        the path to list of paths associated with the expressible meaning with that same
        tagset (which will have to be instantiated the first time each tagset is encountered).
        """
        if self.verbosity > 0:
            print "Constructing expressible meanings..."
        expressible_meanings = []
        for path_string, trie_key_for_that_path_string in self.trie.iteritems():
            if path_string:
                rules_on_that_path = [self.grammar.production_rules[int(i)] for i in path_string.split(',')]
            else:
                rules_on_that_path = []  # An empty path, in the case of paths through symbols with no tags
            all_tags_for_that_path = set()
            for rule in rules_on_that_path:
                all_tags_for_that_path |= set(rule.tags)
            try:
                # If an expressible meaning already exists for this tagset, simply
                # append the trie key for this path to its listing of associated paths
                expressible_meaning = next(em for em in expressible_meanings if em.tags == all_tags_for_that_path)
                expressible_meaning.grammar_paths.append(trie_key_for_that_path_string)
            except StopIteration:
                # We haven't constructed an expressible meaning for that tagset yet, so do
                # so now and pass along this path trie key as its first associated path (more will
                # likely be collected as this loop proceeds)
                meaning_id = len(expressible_meanings)
                expressible_meanings.append(
                    ExpressibleMeaning(
                        meaning_id=meaning_id, tags=all_tags_for_that_path,
                        initial_grammar_path=trie_key_for_that_path_string
                    )
                )
        return expressible_meanings

    def _save_expressible_meanings(self, expressible_meanings_file_location):
        """Save a set of constructed expressible meanings to a file."""
        if self.verbosity > 0:
            print "Saving expressible meanings file..."
        f = open(expressible_meanings_file_location, 'w')
        tag_to_id = self.grammar.tag_to_id
        for expressible_meaning in self.expressible_meanings:
            all_paths_str = ','.join(str(path_trie_key) for path_trie_key in expressible_meaning.grammar_paths)
            all_tags_str = ','.join(tag_to_id[tag] for tag in expressible_meaning.tags)
            line = "{meaning_id}\t{paths}\t{tags}\n".format(
                meaning_id=expressible_meaning.id, paths=all_paths_str, tags=all_tags_str
            )
            f.write(line)
        f.close()

    def _save_grammar(self, grammar_file_location):
        """Write out a JSON file defining the grammar, for use at runtime by Productionist."""
        if self.verbosity > 0:
            print "Saving grammar file..."
        # Prepare a grammar dictionary with the metadata that we need
        grammar_dictionary = {}
        # Add in metadata that we need
        grammar_dictionary['tag_to_id'] = self.grammar.tag_to_id
        grammar_dictionary['id_to_tag'] = self.grammar.id_to_tag
        # Add in the grammar's nonterminal symbols (along with all necessary metadata)
        grammar_dictionary['nonterminal_symbols'] = {}
        for symbol in self.grammar.nonterminal_symbols:
            grammar_dictionary['nonterminal_symbols'][symbol.id] = {
                'name': symbol.name,
                'expansions_are_complete_outputs': symbol.expansions_are_complete_outputs,
                'is_start_symbol': symbol.start_symbol,
                'is_semantically_meaningful': symbol.semantically_meaningful,
                'tags': symbol.tags,
                'production_rules': [
                    {
                        "id": rule.id,
                        "application_frequency": rule.application_frequency,
                        "body": [s.id if type(s) != unicode else s for s in rule.body],
                        "is_semantically_meaningful": rule.semantically_meaningful,
                    }
                    for rule in symbol.production_rules
                ]
            }
        # Export this dictionary to a JSON file (though we'll use the '.grammar' file extension to
        # emphasize that a specific dictionary structure is required)
        with open(grammar_file_location, 'w') as outfile:
            json.dump(grammar_dictionary, outfile)

    def _write_stats_file(self, stats_file_location):
        """Write out a file with stats on this grammar."""
        if self.verbosity > 0:
            print "Saving grammar-statistics file..."
        f = open(stats_file_location, 'w')
        f.write("Total outputs\t{n}\n".format(n=self.total_generable_outputs))
        f.write("Total expressible meanings\t{n}\n".format(n=len(self.expressible_meanings)))
        f.write("Total terminal expansions of nonterminal symbols\n")
        for symbol in self.grammar.nonterminal_symbols:
            f.write("\t{symbol}\t{n}\n".format(symbol=symbol.name, n=symbol.total_generable_variants))
        f.write("Total terminal results of production rules\n")
        for rule in self.grammar.production_rules:
            f.write("\t{rule}\t{n}\n".format(rule=str(rule), n=rule.total_generable_variants))
        f.close()


class ExpressibleMeaning(object):
    """An 'expressible meaning' is a particular meaning (i.e., collection of tags), bundled with
    recipes (i.e., collection of grammar paths) for generating content that will come with those tags.

    The recipe for generating the desired content is specified in the form of a set of possible paths through
    the grammar. Each path is represented as a chain of production rules that, when executed in the given order,
    will produce the desired content.
    """

    def __init__(self, meaning_id, tags, initial_grammar_path, grammar_paths=None):
        """Initialize a ExpressibleMeaning object."""
        self.id = meaning_id
        # A set including all the tags associated with this expressible meaning; these can be thought
        # of as the semantics that are associated with all the paths through the grammar that this
        # expressible meaning indexes
        self.tags = tags
        # A list of all the semantically meaningful paths through the grammar (represented compactly
        # using the trie keys for the paths) that are associated with the semantics of this intermediate
        # representation (i.e., that, if the rules on the path are executed in order, will produce the
        # exact set of tags associated with this expressible meanings)
        if grammar_paths is None:  # Called by Reductionist._construct_expressible_meanings()
            self.grammar_paths = [initial_grammar_path]  # Gets appended to by Reductionist._build_trie()
        else:  # Called by Reductionist._load_expressible_meanings()
            self.grammar_paths = grammar_paths

    def __str__(self):
        """Return string representation."""
        return "An expressible meaning associated with the following tags: {}".format(
            ', '.join(self.tags)
        )


class Grammar(object):
    """A context-free grammar, authored using Expressionist."""

    def __init__(self, grammar_file_location):
        """Initialize a Grammar object."""
        self.start_symbol = None  # Gets set later by self._init_create_start_symbol_and_top_level_production_rules()
        self.nonterminal_symbols = self._init_parse_json_grammar_specification(
            grammar_file_location=grammar_file_location
        )
        self._init_assign_id_numbers_to_all_symbols_and_rules()
        self._init_ground_symbol_references_in_all_production_rule_bodies()
        # Collect all production rules
        self.production_rules = []
        for symbol in self.nonterminal_symbols:
            self.production_rules += symbol.production_rules
        # Collect all terminal symbols
        self.terminal_symbols = []
        for rule in self.production_rules:
            for symbol in rule.body:
                if type(symbol) == unicode and symbol not in self.terminal_symbols:
                    self.terminal_symbols.append(symbol)
        # Have all production rules compile all the tags on the symbols in their rule bodies
        for rule in self.production_rules:
            rule.compile_tags()
        # Compile all tags attached to all symbols in this grammar
        self.tags = set()
        for symbol in self.nonterminal_symbols:
            self.tags |= set(symbol.tags)
        # Build dictionaries mapping individual tags to ID numbers (and vice versa), to allow
        # for efficient storage by Reductionist later on
        self.tag_to_id = {}
        self.id_to_tag = {}
        for i, tag in enumerate(self.tags):
            self.tag_to_id[tag] = str(i)
            self.id_to_tag[str(i)] = tag

    @staticmethod
    def _init_parse_json_grammar_specification(grammar_file_location):
        """Parse a JSON grammar specification exported by Expressionist to instantiate symbols and rules."""
        # Parse the JSON specification to build a dictionary data structure
        symbol_objects = []
        try:
            grammar_dictionary = json.loads(open(grammar_file_location).read())
        except IOError:
            raise Exception(
                "Cannot load grammar -- there is no JSON file located at '{filepath}'".format(
                    filepath=grammar_file_location
                )
            )
        nonterminal_symbol_specifications = grammar_dictionary['nonterminals']
        for name, nonterminal_symbol_specification in nonterminal_symbol_specifications.iteritems():
            expansions_are_complete_outputs = nonterminal_symbol_specification['deep']
            production_rules_specification = nonterminal_symbol_specification['rules']
            tag_dictionary = nonterminal_symbol_specification['markup']
            symbol_object = NonterminalSymbol(
                name=name, expansions_are_complete_outputs=expansions_are_complete_outputs,
                tag_dictionary=tag_dictionary, production_rules_specification=production_rules_specification
            )
            symbol_objects.append(symbol_object)
        return symbol_objects

    def _init_assign_id_numbers_to_all_symbols_and_rules(self):
        """Assigned ID numbers to all symbols and rules in this grammar."""
        next_symbol_id = next_rule_id = 0
        for symbol in self.nonterminal_symbols:
            symbol.id = next_symbol_id
            next_symbol_id += 1
            for rule in symbol.production_rules:
                rule.id = next_rule_id
                next_rule_id += 1

    def _init_ground_symbol_references_in_all_production_rule_bodies(self):
        """Ground all symbol references in production rule bodies to actual NonterminalSymbol objects."""
        for symbol in self.nonterminal_symbols:
            for rule in symbol.production_rules:
                self._init_ground_symbol_references_in_a_rule_body(production_rule=rule)
                # Determine whether this rule is terminal, meaning a rule that merely expands its head
                # to a terminal symbol (we can determine this by looking for symbols that are not of
                # the type unicode, which all terminal symbols will be, since they're just strings)
                rule.terminal = not any(symbol for symbol in rule.body if type(symbol) is not unicode)

    def _init_ground_symbol_references_in_a_rule_body(self, production_rule):
        """Ground all symbol references in the body of this rule to actual NonterminalSymbol objects."""
        rule_body_specification = list(production_rule.body_specification)
        rule_body_with_resolved_symbol_references = []
        for symbol_reference in rule_body_specification:
            if symbol_reference[:2] == '[[' and symbol_reference[-2:] == ']]':
                # We've encountered a reference to a nonterminal symbol, so we need to resolve this
                # reference and append to the list that we're building the nonterminal symbol itself
                symbol_name = symbol_reference[2:-2]
                symbol_object = next(symbol for symbol in self.nonterminal_symbols if symbol.name == symbol_name)
                rule_body_with_resolved_symbol_references.append(symbol_object)
            else:
                # We've encountered a terminal symbol, so we can just append this string itself
                # to the list that we're building
                rule_body_with_resolved_symbol_references.append(symbol_reference)
            production_rule.body = rule_body_with_resolved_symbol_references

    def create_start_symbol_and_top_level_production_rules(self):
        """Create a start symbol for this grammar, along with a set of production rules that will expand it
        into the de facto top-level symbols in the authored grammar (i.e., the ones that appear in no
        production-rule bodies.)
        """
        # Create a start symbol with no markup and no specification of production rules (we'll
        # manually create production rules in the next step here)
        start_symbol = NonterminalSymbol(
            name='START', expansions_are_complete_outputs=True, tag_dictionary=None,
            production_rules_specification=None, start_symbol=True
        )
        next_available_symbol_id = max(self.nonterminal_symbols, key=lambda s: s.id).id + 1
        start_symbol.id = next_available_symbol_id
        # Manually create production rules that may be used to expand this symbol into the de facto
        # top-level symbols in the grammar (i.e., the ones that an author has marked as being symbols
        # whose terminal expansions are complete lines of dialogue)
        de_facto_top_level_symbols = [s for s in self.nonterminal_symbols if s.expansions_are_complete_outputs]
        top_level_production_rules = []
        next_available_rule_id = max(self.production_rules, key=lambda r: r.id).id + 1
        for symbol in de_facto_top_level_symbols:
            production_rule_object = ProductionRule(
                head=start_symbol, body_specification=['[[{symbol_name}]]'.format(symbol_name=symbol.name)],
                application_frequency=1.0
            )
            production_rule_object.id = next_available_rule_id
            next_available_rule_id += 1
            production_rule_object.body = [symbol]
            production_rule_object.compile_tags()
            top_level_production_rules.append(production_rule_object)
        # Save the new symbol and production rules
        start_symbol.production_rules = top_level_production_rules
        self.start_symbol = start_symbol
        self.nonterminal_symbols.append(start_symbol)
        self.production_rules += top_level_production_rules


class NonterminalSymbol(object):
    """A nonterminal symbol in an annotated context-free grammar authored using an Expressionist-like tool."""

    def __init__(self, name, expansions_are_complete_outputs, tag_dictionary, production_rules_specification,
                 start_symbol=False):
        """Initialize a NonterminalSymbol object."""
        self.name = name
        self.id = None
        # Whether an author marked this as a symbol whose terminal expansions are complete outputs
        self.expansions_are_complete_outputs = expansions_are_complete_outputs
        # Whether this is the start symbol in the grammar
        self.start_symbol = start_symbol
        # Reify production rules for expanding this symbol
        self.production_rules = self._init_reify_production_rules(production_rules_specification)
        # Compile all tags attached to this symbol
        self.tags = []
        if tag_dictionary:
            for tagset in tag_dictionary:
                for tag in tag_dictionary[tagset]:
                    tag_str = '{tagset}:{tag}'.format(tagset=tagset, tag=tag)
                    if tag_str not in self.tags:
                        self.tags.append(tag_str)
        # Total number of lines that can be generated by expanding this symbol; this is used to
        # determine the total number of lines that the entire grammar is capable of generating,
        # and it is computed by self.total_number_of_generable_variants() on a call from
        # Reductionist.__init__()
        self.total_generable_variants = None
        # Whether this symbol and/or any of its descendants have tags
        self.semantically_meaningful = None

    def __str__(self):
        """Return string representation."""
        return '[[{name}]]'.format(name=self.name)

    def _init_reify_production_rules(self, production_rules_specification):
        """Instantiate ProductionRule objects for the rules specified in production_rules_specification."""
        production_rule_objects = []
        if production_rules_specification:
            for rule_specification in production_rules_specification:
                body = rule_specification['expansion']
                application_frequency = rule_specification['app_rate']
                production_rule_objects.append(
                    ProductionRule(head=self, body_specification=body, application_frequency=application_frequency)
                )
        return production_rule_objects

    def count_generable_variants(self):
        """Determine the number of unique terminal expansions of this symbol."""
        if not self.total_generable_variants:
            self.total_generable_variants = sum(rule.count_generable_variants() for rule in self.production_rules)
        return self.total_generable_variants


class ProductionRule(object):
    """A production rule in an annotated context-free grammar authored using an Expressionist-like tool."""

    def __init__(self, head, body_specification, application_frequency):
        """Initialize a ProductionRule object.

        'head' is a nonterminal symbol constituting the left-hand side of this rule, while
        'body_specification' defines a sequence of symbols that this rule may be used to expand the head into.
        """
        self.id = None
        self.head = head
        self.body = None  # Gets set by Grammar._init_ground_symbol_references_in_a_rule_body()
        self.terminal = None  # Gets set by Grammar._init_ground_symbol_references_in_a_rule_body()
        self.body_specification = body_specification
        self.body_specification_str = ''.join(body_specification)
        # Specifies the frequency at which this rule will be applied relative to other rules that
        # expand the same head symbol
        self.application_frequency = application_frequency
        # All the tags that are attached to the symbols in the body of this rule; gets set by self.compile_tags()
        self.tags = []
        # Total number of lines that can be generated by firing this rule; this is used to
        # determine the total number of lines that the entire grammar is capable of generating,
        # and it is determined by self.count_generable_variants()
        self.total_generable_variants = None
        # Whether this rule has tags or is the ancestor of any production rule that has tags (i.e.,
        # whether or not it indexes semantic variation, meaning variation in the tags that will come
        # packaged up with content generated by executing this rule); this gets set by
        # Reductionist._determine_if_production_rule_is_semantically_meaningful()
        self.semantically_meaningful = None

    def __str__(self):
        """Return string representation."""
        return '{head} --> {body}'.format(head=self.head, body=self.body_specification_str)

    def compile_tags(self):
        """Compile all tags that are accessible from this production rule, meaning all the tags on all the symbols
        in the body of this rule.
        """
        for symbol in self.body:
            if type(symbol) != unicode:  # i.e., if the symbol is nonterminal
                for tag in symbol.tags:
                    if tag not in self.tags:
                        self.tags.append(tag)

    def count_generable_variants(self):
        """Determine the number of unique terminal executions of this rule."""
        if not self.total_generable_variants:
            self.total_generable_variants = reduce(
                operator.mul, (
                    symbol.count_generable_variants() if type(symbol) is not unicode else 1
                    for symbol in self.body), 1
            )
        return self.total_generable_variants


class Validator(object):
    """A class for validating grammars exported by Expressionist."""

    def __init__(self, grammar):
        """Initialize a Validator object."""
        self.errors = 0
        self.warnings = 0
        self.error_messages = []
        self.warning_messages = []
        # Check for a cycle in the grammar (signaled by a nonterminal symbol being its own descendant, i.e.,
        # appearing in the body of its own production rule or in the body of a production rule that may
        # be recursively called thereby)
        self.descendants_of_symbol = {s: None for s in grammar.nonterminal_symbols}  # To amortize the computation
        self.symbol_associated_with_cycle = None
        self.rule_associated_with_cycle = None
        self._check_whether_cycle_is_present(grammar=grammar)
        if self.symbol_associated_with_cycle:
            self.errors += 1
            self.error_messages.append(
                "[Error] A cycle was detected. It is associated with the nonterminal symbol '[[{symbol}]]'".format(
                    symbol=self.symbol_associated_with_cycle.name
                ) +
                ", which recursively references it itself via the variant '{variant}'".format(
                    variant=self.rule_associated_with_cycle
                )
            )
        # Make sure there is at least one top-level symbol; if not, the grammar cannot generate content
        top_level_symbols = [
            s for s in grammar.nonterminal_symbols if s.expansions_are_complete_outputs and
            s.name != "START"
        ]
        if not top_level_symbols:
            self.warnings += 1
            self.warning_messages.append(
                "[Warning] There are no top-level nonterminal symbols (denoted by asterisks in the Expressionist"
                "interface) -- this means that no content can be generated."
            )

    def _check_whether_cycle_is_present(self, grammar):
        """Do grammar traversal that will trigger an error (for exceeding maximum recursive depth) if
        a cycle is present.
        """
        for symbol in grammar.nonterminal_symbols:
            try:
                self._collect_descendants_of_a_nonterminal_symbol(
                    nonterminal_symbol=symbol, ultimately_checking_for=symbol
                )
            except RuntimeError:
                break

    def _collect_descendants_of_a_nonterminal_symbol(self, nonterminal_symbol, ultimately_checking_for):
        """Collect all descendant nonterminal symbols of the given nonterminal symbol."""
        if self.descendants_of_symbol[nonterminal_symbol]:
            return self.descendants_of_symbol[nonterminal_symbol]
        descendants = set()
        for production_rule in nonterminal_symbol.production_rules:
            descendants |= self._collect_descendants_of_a_production_rule(
                production_rule=production_rule, ultimately_checking_for=ultimately_checking_for
            )
        self.descendants_of_symbol[nonterminal_symbol] = descendants
        return descendants

    def _collect_descendants_of_a_production_rule(self, production_rule, ultimately_checking_for):
        """Collect all descendant nonterminal symbols of the given production rule."""
        descendants = set()
        for symbol in production_rule.body:
            if type(symbol) is not unicode:
                if symbol is ultimately_checking_for:
                    # We found a cycle; record information about which symbol completed a cycle (referenced
                    # itself recursively) and which rule completed the cycle
                    self.symbol_associated_with_cycle = symbol
                    self.rule_associated_with_cycle = production_rule
                descendants.add(symbol)
                descendants |= self._collect_descendants_of_a_nonterminal_symbol(
                    nonterminal_symbol=symbol, ultimately_checking_for=ultimately_checking_for
                )
        return descendants


if __name__ == "__main__":
    # Parse the command-line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "content_bundle_name",
        help="the name to be used across the bundle of content files that Reductionist will generate; e.g.,"
             "'jukeJoint', which would produce 'jukeJoint.grammar', 'jukeJoint.trie', and 'jukeJoint.meanings'"
    )
    parser.add_argument(
        "grammar_file",
        help="the full filepath to a grammar file exported by Expressionist"
    )
    parser.add_argument(
        "output_dir",
        help="the full filepath to the directory that output files generated by Reductionist should be written to"
    )
    parser.add_argument(
        "--verbosity",
        help="how verbose Reductionist's debug text should be (0=no debug text, 1=more debug text, 2=most debug text)",
        type=int,
        default=0
    )
    args = parser.parse_args()
    # Prepare the full path that output files will be written to
    output_path_and_filename = args.output_dir
    if output_path_and_filename[-1] != '/':
        output_path_and_filename += '/'
        output_path_and_filename += args.content_bundle_name
    # Index the grammar and save out the resulting files (content file [.content], trie file [.marisa], and
    # expressible meanings file [.meanings])
    reductionist = Reductionist(
        path_to_input_content_file=args.grammar_file,
        path_to_write_output_files_to=output_path_and_filename,
        verbosity=args.verbosity
    )
    if not reductionist.validator.errors:
        print "\n--Success! Indexed this grammar's {n} generable lines to infer {m} expressible meanings.--".format(
            n=reductionist.total_generable_outputs,
            m=len(reductionist.expressible_meanings)
        )
    else:
        print "\n--Errors--"
        for error_message in reductionist.validator.error_messages:
            print '\n{msg}'.format(msg=error_message)
    if reductionist.validator.warnings:
        print "\n--Warnings--"
        for warning_message in reductionist.validator.warning_messages:
            print '\n{msg}'.format(msg=warning_message)
