# Commune Nominator DAO

This bot is designed to manage the nomination and removal of modules from a whitelist using a multisignature address stored as a global parameter. The bot interacts with users through Discord commands. For better understanding please refer to the following issue [initial-issue](https://github.com/agicommies/subspace-network/issues/40)

## Storage

The bot securely stores all private keys as environment variables. These keys must add up to the exact multisignature address of the `whitelist_nominator`, which is stored as a global parameter.

## Discord Commands

### General Commands

- `/apply`: Allows anyone to apply for module whitelisting by providing the following information:
  - SS58 address of the module
  - Description of what the module does
  - Module endpoint information
  - Team members (developers of the module)
  - GitHub, GitLab, or any other repository link (code must be open source)

  After the command is executed, the bot displays a nicely formatted message, and the SS58 address of the module serves as the request ID.

### Module Nominator Commands

Users with the "module_nominator" role in the Discord server have access to the following commands:

- [x] `/nominate <ss58_key>`: Starts a ticket for nominating a module for the whitelist.
- [x] `/remove <ss58_key> <reason>`: Starts a ticket for removing a module from the whitelist.
- [ ] `/addvoter <discord_tag>`: Creates a new multisig key and sends the user a direct message with an introduction (guideline and commands).
- [ ] `/kickvoter <discord_tag>`: Deletes the associated multisig key and sends the user a direct message informing them of their removal.
- [x] `/stats`: Lists a table of members and their `multisig_participation_count` and `multisig_abscence_count`, ranked by participation.
- [x] `/help`: Posts an informational message.

## Contributing

Contributions to this project are welcome. Please submit a pull request or open an issue on the GitHub repository.