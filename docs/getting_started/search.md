# Search Documentation

## Overview
Our search interface helps you find medical entries for manual labeling. The page contains three core components that generate navigable queues of texts:

1. **Include field** - For content that must appear in results
2. **Exclude field** - For content that must not appear in results
3. **Results control** - Manages how many entries to return

Additionally, a separate Random Generator section allows creating queues of random entries. All operations create queues you can navigate for manual labeling.

![Search Interface](images/search-interface.png)

!!! tip "How to Add Search Terms"
    To add items to Include or Exclude fields:
    1. Type a word or multiple words (phrase)
    2. Press <kbd>Enter</kbd> to add it
    3. Repeat to add multiple items

## Search Components

### 1. Include Field
- **Purpose**: Define what should appear in your results
- **How to use**:
  - Type a single word (`diabetes`) or multiple words (`heart disease`)
  - Press <kbd>Enter</kbd> to add it to your search criteria
- **Behavior**:
  - **Single words**: Finds variations and partial matches
    *Example: `hepat` finds hepatitis, hepatic*
  - **Multiple words**: Treated as exact phrases
    *Example: `liver function` finds the exact phrase "liver function"*
- **Combination**: OR logic (finds entries matching ANY item)

### 2. Exclude Field
- **Purpose**: Filter out unwanted content
- **Behavior**: Same matching rules as Include field
- **Combination**: Filters out entries matching ANY item

### 3. Results Control
- **Number of entries**: Set how many results to return (1-1000)

## Key Matching Features
- **Partial word matching**: `cardio` finds cardiovascular
- **Typo tolerance**: `diabete` finds diabetes
- **Automatic phrase detection**: Multiple words are treated as exact phrases

## Usage Examples

### Basic Search
1. **Find diabetes-related entries**
   Include: `diabetes`
   → Creates queue with matching entries

2. **Find insulin OR metformin**
   Include: `insulin` + `metformin`
   → Queue contains entries with either term

### Advanced Search
**Find adult heart disease cases**
Include: `cardio` + `heart disease`
Exclude: `pediatric`
→ Queue excludes pediatric entries while finding heart disease mentions

## Random Generator
- **Location**: Separate section at the bottom of the page
- **Purpose**: Generate completely random entries
- **How to use**:
  1. Enter number of texts to generate (1-1000)
  2. Click "Generate Queue"
- **Creates**: Queue of random entries ignoring all search criteria
- **Use case**: Diverse sampling and exploratory labeling

## Result Handling
- All operations create navigable queues:
  - Searches create queues matching your criteria
  - Random Generator creates queues of random entries
- Queues appear immediately after generation
- Navigate sequentially through entries
- Label each entry directly in the queue interface

Simply add your terms, set the number of results, and create your labeling queue!